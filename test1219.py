# whatever

import os
import shutil
from pathlib import Path
import random
import string
import requests
import time
import csv
from datetime import datetime, timedelta
from collections import defaultdict
import pandas as pd
import json
import logging
from logging.handlers import RotatingFileHandler
import concurrent.futures
from threading import Lock
import gc  # Add explicit import for garbage collector
import psutil  # Add explicit import for process utilities
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from selenium.webdriver.common.action_chains import ActionChains
import threading

# ==== 基础配置 ====
BASE_DIR = "/home/carl_zhou/sock_puppet"
DIRS = {
    'logs': f"{BASE_DIR}/logs",
    'checkpoints': f"{BASE_DIR}/checkpoints",
    'results': f"{BASE_DIR}/results",
    'state_videos': f"{BASE_DIR}/videos/state",
    'non_state_videos': f"{BASE_DIR}/videos/non",
    'pretrain': f"{BASE_DIR}/pretrain",
    'batch_logs': f"{BASE_DIR}/logs/batches",
    'cookies': f"{BASE_DIR}/cookies"
}


# 全局浏览器管理器
class BrowserManager:
    def __init__(self):
        self.browsers = {}
        self.browser_lock = Lock()
        self.success_count = 0
        self.required_count = 0

    def get_driver(self, username):
        """获取指定用户名的浏览器实例"""
        with self.browser_lock:
            driver = self.browsers.get(username)
            if not driver:
                logger.warning(f"找不到用户 {username} 的浏览器实例")
                return None

            # 验证现有实例是否有效
            try:
                driver.driver.current_url  # 测试会话是否有效
                return driver
            except Exception as e:
                logger.warning(f"用户 {username} 的浏览器实例无效: {str(e)}")
                self.browsers.pop(username, None)
                return None

    def create_all_browsers(self, total_accounts_per_group, groups, cleanup_existing=False):
        """并行创建所有浏览器实例"""
        total_accounts = total_accounts_per_group * len(groups)
        self.required_count = total_accounts
        logger.info(f"开始并行创建 {total_accounts} 个浏览器实例...")

        # 只在需要时清理浏览器
        if cleanup_existing:
            self.cleanup_all_browsers()

        # 用于存储成功创建的账户信息
        accounts = []
        account_creation_lock = Lock()

        def create_single_browser(group):
            try:
                username = generate_username()
                driver = BilibiliDriver()

                if not driver.get("https://www.bilibili.com"):
                    raise Exception("无法访问B站首页")

                cookies = driver.driver.get_cookies()
                save_cookies(username, cookies)

                account = {
                    'username': username,
                    'sex': random.choice(['male', 'female']),
                    'group': group,
                    'watched_videos': [],
                    'completed_videos_count': 0
                }

                with self.browser_lock:
                    self.browsers[username] = driver
                    self.success_count += 1

                with account_creation_lock:
                    accounts.append(account)

                logger.info(f"成功创建账户 {username} ({group}) [{self.success_count}/{self.required_count}]")
                return True

            except Exception as e:
                logger.error(f"创建账户失败: {str(e)}")
                if driver:
                    try:
                        driver.close()
                    except:
                        pass
                return False

        # 创建所有需要的账户任务
        tasks = []
        for group in groups:
            for _ in range(total_accounts_per_group):
                tasks.append(group)

        # 并行执行账户创建
        with concurrent.futures.ThreadPoolExecutor(max_workers=total_accounts) as executor:
            futures = [executor.submit(create_single_browser, group) for group in tasks]
            concurrent.futures.wait(futures)

        # 检查是否所有需要的账户都创建成功
        if self.success_count < self.required_count:
            logger.error(f"账户创建不完整: 需要 {self.required_count} 个, 成功 {self.success_count} 个")
            # 清理所有实例，重新开始
            self.cleanup_all_browsers()
            return None

        return accounts

    def cleanup_all_browsers(self):
        """改进的浏览器清理方法"""
        cleanup_count = 0
        error_count = 0

        with self.browser_lock:
            if not self.browsers:
                logger.info("没有需要清理的浏览器实例")
                return

            browsers_to_cleanup = list(self.browsers.items())
            logger.info(f"开始清理 {len(browsers_to_cleanup)} 个浏览器实例...")

            for username, driver in browsers_to_cleanup:
                try:
                    if driver and driver.driver:
                        try:
                            driver.driver.get("about:blank")
                            driver.driver.quit()
                            cleanup_count += 1
                            logger.info(f"成功清理浏览器实例: {username}")
                        except Exception as e:
                            logger.error(f"清理浏览器失败 ({username}): {str(e)}")
                            error_count += 1
                except Exception as e:
                    logger.error(f"清理过程出错 ({username}): {str(e)}")
                    error_count += 1
                finally:
                    self.browsers.pop(username, None)

            self.success_count = 0
            self.browsers.clear()
            gc.collect()
            logger.info(f"浏览器清理完成: 成功 {cleanup_count} 个, 失败 {error_count} 个")


class DirectoryManager:
    @staticmethod
    def clean_directories():
        """清空所有工作目录"""
        for dir_path in DIRS.values():
            try:
                if os.path.exists(dir_path):
                    shutil.rmtree(dir_path)
                os.makedirs(dir_path, exist_ok=True)
                logger.info(f"清理并重建目录: {dir_path}")
            except Exception as e:
                logger.error(f"清理目录失败 {dir_path}: {str(e)}")

    @staticmethod
    def ensure_directories():
        """确保所有必要的目录存在"""
        for dir_path in DIRS.values():
            os.makedirs(dir_path, exist_ok=True)

def setup_logging():
    logger = logging.getLogger('bilibili_experiment')
    logger.setLevel(logging.INFO)

    file_handler = RotatingFileHandler(
        f"{DIRS['logs']}/experiment.log",
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding='utf-8'
    )
    file_handler.setLevel(logging.INFO)

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)

    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    file_handler.setFormatter(formatter)
    console_handler.setFormatter(formatter)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    return logger


logger = setup_logging()


class BatchManager:
    def process_batch(self, batch_number, total_batches, accounts, exp_manager):
        """处理单个批次，确保所有账号都收集到数据"""
        try:
            logger.info(f"开始处理批次 {batch_number}/{total_batches}")

            # 跟踪每个组的数据收集情况
            group_stats = {
                'state': {'required': 5, 'completed': 0, 'accounts': []},
                'non-state': {'required': 5, 'completed': 0, 'accounts': []},
                'control': {'required': 5, 'completed': 0, 'accounts': []}
            }

            all_results = []
            max_retries_per_account = 5

            while True:
                # 检查是否所有组都完成
                all_completed = all(
                    stats['completed'] >= stats['required']
                    for stats in group_stats.values()
                )

                if all_completed:
                    break

                # 收集未完成账号的数据
                for account in accounts:
                    group = account['group']

                    # 如果这个组已经收集够了数据，跳过
                    if group_stats[group]['completed'] >= group_stats[group]['required']:
                        continue

                    # 如果这个账号已经成功，跳过
                    if account['username'] in group_stats[group]['accounts']:
                        continue

                    # 收集这个账号的数据
                    retry_count = 0
                    while retry_count < max_retries_per_account:
                        try:
                            results = exp_manager.collect_data_parallel_for_account(account)

                            # 验证数据完整性
                            if self.verify_data_completeness(results, account):
                                all_results.extend(results)
                                group_stats[group]['completed'] += 1
                                group_stats[group]['accounts'].append(account['username'])
                                logger.info(f"账号 {account['username']} ({group}) 数据收集完成 "
                                            f"[{group_stats[group]['completed']}/{group_stats[group]['required']}]")
                                break
                            else:
                                logger.warning(f"账号 {account['username']} 数据不完整，重试...")
                                retry_count += 1
                                if retry_count < max_retries_per_account:
                                    time.sleep(random.uniform(10, 20))

                        except Exception as e:
                            logger.error(f"处理账号 {account['username']} 失败: {str(e)}")
                            retry_count += 1
                            if retry_count < max_retries_per_account:
                                time.sleep(random.uniform(10, 20))
                                continue

                    # 如果这个账号重试耗尽仍然失败，创建新账号替代
                    if retry_count >= max_retries_per_account:
                        logger.warning(f"账号 {account['username']} 重试耗尽，创建新账号...")
                        new_account = self.create_replacement_account(group)
                        if new_account:
                            accounts.append(new_account)
                            logger.info(f"创建替代账号成功: {new_account['username']}")

                # 检查是否需要终止（预防无限循环）
                if all(len(stats['accounts']) >= stats['required'] * 2 for stats in group_stats.values()):
                    raise Exception("尝试次数过多，无法完成数据收集")

                time.sleep(5)  # 避免过于频繁的重试

            # 验证最终结果
            if not self.verify_batch_completeness(all_results, group_stats):
                raise Exception("批次数据验证失败")

            # 保存结果
            exp_manager.save_collected_videos(all_results)

            # 打印统计信息
            self.print_batch_stats(group_stats)

            return all_results

        except Exception as e:
            logger.error(f"批次 {batch_number} 处理失败: {str(e)}")
            return None

    def _verify_data_progress(self, results):
        """验证数据收集进度"""
        if not results:
            return False, 0, 0

        homepage_count = len([r for r in results if r['source'] == 'homepage'])
        related_count = len([r for r in results if r['source'] == 'related'])

        target_homepage = 30
        target_related = 300

        homepage_progress = (homepage_count / target_homepage) * 100
        related_progress = (related_count / target_related) * 100

        is_complete = homepage_count >= 27 and related_count >= 270

        return is_complete, homepage_progress, related_progress
    def verify_data_completeness(self, results, account):
        """验证单个账号的数据是否完整"""
        if not results:
            return False

        # 计算这个账号的数据统计
        homepage_count = len([r for r in results if r['source'] == 'homepage'])
        related_count = len([r for r in results if r['source'] == 'related'])

        # 验证数据量是否符合预期
        # 首页应该有30个视频，每个视频应该有10个相关推荐
        expected_homepage = 30
        expected_related = expected_homepage * 10

        # 允许一定的误差（例如90%的完整度）
        homepage_threshold = expected_homepage * 0.9
        related_threshold = expected_related * 0.9

        is_complete = (homepage_count >= homepage_threshold and
                       related_count >= related_threshold)

        if not is_complete:
            logger.warning(f"账号 {account['username']} 数据不完整: "
                           f"首页视频 {homepage_count}/{expected_homepage}, "
                           f"相关视频 {related_count}/{expected_related}")

        return is_complete

    def verify_batch_completeness(self, all_results, group_stats):
        """验证整个批次的数据是否完整"""
        if not all_results:
            return False

        # 按组统计数据
        group_counts = defaultdict(int)
        for result in all_results:
            group_counts[result['group']] += 1

        # 验证每个组是否都达到最小要求
        min_required_per_account = 330  # 30个首页视频 * (1 + 10个相关推荐)
        for group, stats in group_stats.items():
            required_count = stats['required'] * min_required_per_account * 0.9  # 允许10%的误差
            if group_counts[group] < required_count:
                logger.error(f"{group}组数据不完整: {group_counts[group]}/{required_count}")
                return False

        return True

    def create_replacement_account(self, group):
        """创建替代账号"""
        try:
            username = generate_username()
            driver = BilibiliDriver()

            if not driver.get("https://www.bilibili.com"):
                return None

            cookies = driver.driver.get_cookies()
            if not cookies:
                return None

            save_cookies(username, cookies)

            account = {
                'username': username,
                'sex': random.choice(['male', 'female']),
                'group': group,
                'watched_videos': [],
                'completed_videos_count': 0
            }

            return account

        except Exception as e:
            logger.error(f"创建替代账号失败: {str(e)}")
            return None

    def print_batch_stats(self, group_stats):
        """打印批次统计信息"""
        logger.info("\n=== 批次完成统计 ===")
        for group, stats in group_stats.items():
            logger.info(f"{group}组: 完成 {stats['completed']}/{stats['required']} 个账号")
            logger.info(f"成功账号: {', '.join(stats['accounts'])}")
        logger.info("==================\n")


class ResourceManager:
    def __init__(self):
        self.active_drivers = set()
        self.driver_lock = Lock()

    def cleanup_old_logs(self, days=7):
        """清理超过指定天数的日志文件"""
        try:
            cutoff = datetime.now() - timedelta(days=days)
            for log_dir in [DIRS['logs'], DIRS['batch_logs']]:
                for file in os.listdir(log_dir):
                    file_path = os.path.join(log_dir, file)
                    if os.path.isfile(file_path):
                        file_time = datetime.fromtimestamp(os.path.getmtime(file_path))
                        if file_time < cutoff:
                            os.remove(file_path)
                            logger.info(f"已删除过期日志文件: {file_path}")
        except Exception as e:
            logger.error(f"清理日志文件失败: {str(e)}")

    def cleanup_old_checkpoints(self, keep_last=5):
        """只保留最近的N个检查点文件"""
        try:
            checkpoint_files = sorted(
                [f for f in os.listdir(DIRS['checkpoints']) if f.startswith('checkpoint_')],
                key=lambda x: os.path.getmtime(os.path.join(DIRS['checkpoints'], x)),
                reverse=True
            )

            for checkpoint in checkpoint_files[keep_last:]:
                file_path = os.path.join(DIRS['checkpoints'], checkpoint)
                os.remove(file_path)
                logger.info(f"已删除旧检查点文件: {file_path}")
        except Exception as e:
            logger.error(f"清理检查点文件失败: {str(e)}")

    def register_driver(self, driver):
        """注册新的driver实例"""
        with self.driver_lock:
            self.active_drivers.add(driver)

    def unregister_driver(self, driver):
        """注销driver实例"""
        with self.driver_lock:
            self.active_drivers.discard(driver)

    def cleanup_all_drivers(self):
        """清理所有活动的driver实例"""
        with self.driver_lock:
            for driver in self.active_drivers:
                try:
                    driver.close()
                except Exception as e:
                    logger.error(f"清理driver失败: {str(e)}")
            self.active_drivers.clear()


class ExperimentMonitor:
    def __init__(self):
        self.start_time = None
        self.stats = {
            'total_accounts': 0,
            'successful_accounts': 0,
            'failed_accounts': 0,
            'total_videos': 0,
            'successful_videos': 0,
            'failed_videos': 0,
            'errors': defaultdict(int)
        }
        self.stats_lock = Lock()

    def start_experiment(self):
        """开始实验计时"""
        self.start_time = datetime.now()

    def record_error(self, error_type, error_msg):
        """记录错误信息"""
        with self.stats_lock:
            self.stats['errors'][f"{error_type}: {error_msg}"] += 1

    def update_stats(self, **kwargs):
        """更新统计信息"""
        with self.stats_lock:
            for key, value in kwargs.items():
                if key in self.stats:
                    self.stats[key] += value

    def generate_report(self):
        """生成实验报告"""
        if not self.start_time:
            return "实验未开始"

        duration = datetime.now() - self.start_time
        success_rate = (self.stats['successful_accounts'] / self.stats['total_accounts'] * 100
                        if self.stats['total_accounts'] > 0 else 0)

        report = f"""
实验统计报告
====================
运行时间: {duration}
账户统计:
- 总账户数: {self.stats['total_accounts']}
- 成功账户数: {self.stats['successful_accounts']}
- 失败账户数: {self.stats['failed_accounts']}
- 成功率: {success_rate:.2f}%

视频统计:
- 总视频数: {self.stats['total_videos']}
- 成功观看数: {self.stats['successful_videos']}
- 失败观看数: {self.stats['failed_videos']}
- 视频成功率: {(self.stats['successful_videos'] / self.stats['total_videos'] * 100) if self.stats['total_videos'] > 0 else 0:.2f}%

错误统计:
"""
        for error, count in self.stats['errors'].items():
            report += f"- {error}: {count}次\n"

        return report


class BilibiliAPI:
    def __init__(self):
        self.base_url = "https://api.bilibili.com"
        self.session = requests.Session()
        self.user_agents = [
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Edge/91.0.864.59',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/92.0.4515.107 Safari/537.36',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Safari/605.1.15'
        ]
        self.request_lock = Lock()
        self.last_request_time = time.time()
        self.error_count = 0
        self.MAX_ERROR_COUNT = 5

    def set_cookies(self, cookies):
        """设置session cookies"""
        if cookies:
            for cookie in cookies:
                self.session.cookies.set(cookie['name'], cookie['value'])

    def _get_random_ua(self):
        """获取随机User-Agent"""
        return random.choice(self.user_agents)

    def _should_reset_error_count(self):
        """检查是否需要重置错误计数"""
        if self.error_count >= self.MAX_ERROR_COUNT:
            logger.warning(f"连续错误次数达到{self.MAX_ERROR_COUNT}次，进入长时间休息...")
            time.sleep(random.uniform(300, 600))
            self.error_count = 0
            return True
        return False

    def get_homepage_videos(self):
        """获取首页推荐视频的改进版本"""
        try:
            endpoint = f"{self.base_url}/x/web-interface/wbi/index/top/feed/rcmd"

            # 扩展请求参数
            params = {
                'web_location': 1430650,
                'ps': 30,
                'fresh_type': 4,
                'feed_version': 'V9',
                'fresh_idx': random.randint(1, 5),  # 随机化fresh_idx
                'fresh_idx_1h': random.randint(1, 5),
                'brush': random.randint(1, 3),
                '_': int(time.time() * 1000)  # 添加时间戳
            }

            # 扩展请求头
            headers = {
                'User-Agent': self._get_random_ua(),
                'Referer': 'https://www.bilibili.com',
                'Origin': 'https://www.bilibili.com',
                'Accept': 'application/json, text/plain, */*',
                'Accept-Encoding': 'gzip, deflate, br',
                'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
                'Cache-Control': 'no-cache',
                'Connection': 'keep-alive',
                'Pragma': 'no-cache',
                'Sec-Ch-Ua': '"Not_A Brand";v="8", "Chromium";v="120"',
                'Sec-Ch-Ua-Mobile': '?0',
                'Sec-Ch-Ua-Platform': '"Windows"',
                'Sec-Fetch-Dest': 'empty',
                'Sec-Fetch-Mode': 'cors',
                'Sec-Fetch-Site': 'same-site'
            }

            # 添加随机延迟
            time.sleep(random.uniform(1, 3))

            response = self.session.get(
                endpoint,
                params=params,
                headers=headers,
                timeout=30
            )

            if response.status_code == 200:
                data = response.json()
                if data and data.get('code') == 0:
                    items = data.get('data', {}).get('item', [])
                    if items:
                        return items
                    else:
                        logger.warning(f"获取到的视频列表为空: {data.get('message', '未知原因')}")
                else:
                    logger.warning(f"API返回错误: {data.get('message', '未知错误')}, code: {data.get('code')}")
            else:
                logger.warning(f"请求失败，状态码: {response.status_code}")

            return []
        except Exception as e:
            logger.error(f"获取首页视频失败: {str(e)}")
            return []

    def get_related_videos(self, bvid, max_count=10):
        """获取视频的相关推荐"""
        try:
            endpoint = f"{self.base_url}/x/web-interface/archive/related"
            params = {
                'bvid': bvid
            }
            headers = {
                'User-Agent': self._get_random_ua(),
                'Referer': f'https://www.bilibili.com/video/{bvid}'
            }

            response = self.session.get(
                endpoint,
                params=params,
                headers=headers,
                timeout=30
            )

            if response.status_code == 200:
                data = response.json()
                if data and data.get('code') == 0:
                    related_videos = data.get('data', [])[:max_count]  # 只取前10个
                    return related_videos
            return []
        except Exception as e:
            logger.error(f"获取相关视频失败: {str(e)}")
            return []

    def request_with_retry(self, endpoint, params=None, max_retries=3):
        """带重试机制的请求方法"""
        retry_count = 0
        while retry_count < max_retries:
            try:
                # 限制请求频率
                with self.request_lock:
                    current_time = time.time()
                    if current_time - self.last_request_time < 1:  # 至少间隔1秒
                        time.sleep(1 - (current_time - self.last_request_time))

                    headers = {
                        'User-Agent': self._get_random_ua(),
                        'Referer': 'https://www.bilibili.com'
                    }

                    response = self.session.get(endpoint, params=params, headers=headers, timeout=30)
                    self.last_request_time = time.time()

                    if response.status_code == 200:
                        try:
                            data = response.json()
                            if data.get('code') == 0:
                                self.error_count = 0  # 成功后重置错误计数
                                return data
                            else:
                                logger.warning(f"B站API返回错误: {data.get('message', '未知错误')}")
                        except ValueError:
                            logger.error("解析JSON响应失败")

                # 请求失败，增加错误计数
                self.error_count += 1

                # 检查是否需要长时间休息
                if self._should_reset_error_count():
                    retry_count = 0  # 重置重试次数
                    continue

            except Exception as e:
                logger.error(f"请求失败 (尝试 {retry_count + 1}/{max_retries}): {str(e)}")

            # 增加重试延迟
            retry_delay = min(2 ** retry_count * 5, 60)  # 指数退避，最长60秒
            time.sleep(retry_delay)
            retry_count += 1

        return None

    def _wait_between_requests(self):
        """请求之间的等待"""
        with self.request_lock:
            current_time = time.time()
            # 确保请求间隔至少2秒
            if current_time - self.last_request_time < 2:
                sleep_time = 2 - (current_time - self.last_request_time)
                time.sleep(sleep_time)
            self.last_request_time = time.time()

    def _handle_request_error(self, error_msg):
        """处理请求错误"""
        self.error_count += 1
        if self.error_count >= self.MAX_ERROR_COUNT:
            sleep_time = random.uniform(60, 120)  # 错误过多时休息1-2分钟
            logger.warning(f"连续错误次数过多，休息 {sleep_time:.1f} 秒")
            time.sleep(sleep_time)
            self.error_count = 0

    def _smart_request_control(self):
        """智能请求控制"""
        try:
            with self.request_lock:
                current_time = time.time()
                elapsed = current_time - self.last_request_time

                if elapsed < 1:  # 最小间隔1秒
                    time.sleep(1 - elapsed)

                # 根据错误计数动态调整等待时间
                if self.error_count > 0:
                    wait_time = min(self.error_count * 2, 10)  # 最多等待10秒
                    time.sleep(wait_time)

                # 随机添加小延迟
                time.sleep(random.uniform(0.1, 0.5))

                self.last_request_time = time.time()

        except Exception as e:
            logger.error(f"请求控制出错: {str(e)}")
            time.sleep(1)  # 发生错误时的保底延迟


class BilibiliDriver:
    def __init__(self, profile_id=None):
        self.driver = None
        self.profile_id = profile_id
        self.profile_dir = f"{BASE_DIR}/profiles/{profile_id}" if profile_id else None
        success = self.init_driver()
        if not success:
            raise Exception("Failed to initialize driver")

    def init_driver(self, max_retries=3):
        for attempt in range(max_retries):
            try:
                options = webdriver.ChromeOptions()

                # 调整Headless模式的设置
                options.add_argument('--headless=new')  # 使用新版headless模式

                # 核心稳定性配置
                options.add_argument('--no-sandbox')
                options.add_argument('--disable-dev-shm-usage')
                options.add_argument('--disable-gpu')

                # 添加稳定性配置
                options.add_argument('--disable-extensions')
                options.add_argument('--disable-logging')
                options.add_argument('--ignore-certificate-errors')
                options.add_argument('--ignore-ssl-errors')
                options.add_argument('--disable-web-security')
                options.add_argument('--disable-features=NetworkService')
                options.add_argument('--force-color-profile=srgb')
                options.add_argument('--disable-blink-features=AutomationControlled')
                options.add_argument('--use-fake-ui-for-media-stream')

                # 设置浏览器窗口大小
                options.add_argument('--window-size=1920,1080')

                # 添加随机UA
                user_agent = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'
                options.add_argument(f'--user-agent={user_agent}')

                # 内存优化配置
                options.add_argument('--js-flags="--max-old-space-size=512"')
                options.add_argument('--disable-javascript-harmony-shipping')

                if self.profile_dir:
                    os.makedirs(self.profile_dir, exist_ok=True)
                    options.add_argument(f'user-data-dir={self.profile_dir}')

                # 添加实验性配置
                options.add_experimental_option('excludeSwitches', ['enable-automation'])
                options.add_experimental_option('useAutomationExtension', False)

                # 设置服务日志级别
                service = webdriver.ChromeService(
                    executable_path='/usr/local/bin/chromedriver',
                    log_output=os.path.join(DIRS['logs'], 'chromedriver.log'),
                    service_args=['--verbose']
                )

                # 初始化driver
                self.driver = webdriver.Chrome(service=service, options=options)

                # 设置超时时间
                self.driver.set_page_load_timeout(30)
                self.driver.set_script_timeout(30)
                self.driver.implicitly_wait(10)

                # 验证浏览器是否正常工作
                self.driver.get("about:blank")
                time.sleep(2)  # 等待浏览器完全初始化

                return True

            except Exception as e:
                logger.error(f"Driver初始化失败 (尝试 {attempt + 1}/{max_retries}): {str(e)}")
                if self.driver:
                    try:
                        self.driver.quit()
                    except:
                        pass
                    self.driver = None

                # 增加重试间隔
                if attempt < max_retries - 1:
                    sleep_time = (attempt + 1) * 5  # 递增等待时间
                    logger.info(f"等待 {sleep_time} 秒后重试...")
                    time.sleep(sleep_time)

        return False

    def ensure_session_valid(self):
        """确保浏览器会话有效"""
        try:
            self.driver.current_url
            return True
        except Exception as e:
            logger.warning(f"会话失效，尝试重新初始化: {str(e)}")
            try:
                if self.driver:
                    try:
                        self.driver.quit()
                    except:
                        pass
                return self.init_driver()
            except Exception as e:
                logger.error(f"重新初始化失败: {str(e)}")
                return False

    def get(self, url):
        """访问URL的改进方法"""
        max_retries = 3
        for attempt in range(max_retries):
            try:
                if not self.ensure_session_valid():
                    if attempt == max_retries - 1:
                        return False
                    time.sleep(5)
                    continue

                self.driver.get(url)
                return True

            except Exception as e:
                logger.error(f"访问URL失败 {url}: {str(e)}")
                if attempt < max_retries - 1:
                    time.sleep(5)
                    continue
        return False

    def wait_for_element_safely(self, by, value, timeout=30):
        """安全地等待元素加载"""
        try:
            element = WebDriverWait(self.driver, timeout).until(
                EC.presence_of_element_located((by, value))
            )
            return element
        except TimeoutException:
            logger.warning(f"等待元素超时: {value}")
            return None
        except Exception as e:
            logger.warning(f"等待元素失败 {value}: {str(e)}")
            return None

    def watch_video(self, url, duration=30, timeout=60):
        """改进的视频观看方法"""
        start_time = time.time()
        max_retries = 3

        for attempt in range(max_retries):
            try:
                # 1. 加载视频页面
                self.driver.get(url)
                time.sleep(3)  # 等待页面开始加载

                # 2. 等待视频播放器加载
                video_element = None
                for selector in ['video', '.bilibili-player-video video', '#bilibili-player video']:
                    try:
                        video_element = WebDriverWait(self.driver, 20).until(
                            EC.presence_of_element_located((By.CSS_SELECTOR, selector))
                        )
                        if video_element:
                            break
                    except:
                        continue

                # 检查是否存在视频不可用的提示
                try:
                    error_elements = self.driver.find_elements(By.CSS_SELECTOR, '.error-text, .error-wrap')
                    for error_elem in error_elements:
                        if error_elem.is_displayed():
                            logger.warning(f"视频不可用: {url}")
                            return None  # 返回None表示视频确实不可用
                except:
                    pass

                if not video_element:
                    logger.warning(f"尝试 {attempt + 1}: 无法找到视频元素")
                    if attempt < max_retries - 1:
                        time.sleep(random.uniform(3, 5))
                    continue

                # 3. 确保视频开始播放
                play_success = self.driver.execute_script("""
                    var video = document.querySelector('video');
                    if(video) {
                        video.play();
                        // 尝试跳过广告
                        if(document.querySelector('.bilibili-player-video-btn-jump')) {
                            document.querySelector('.bilibili-player-video-btn-jump').click();
                        }
                        return true;
                    }
                    return false;
                """)

                if not play_success:
                    logger.warning(f"尝试 {attempt + 1}: 无法播放视频")
                    if attempt < max_retries - 1:
                        time.sleep(random.uniform(3, 5))
                    continue

                # 4. 监控播放进度
                last_time = 0
                stall_start = None
                progress_check_start = time.time()

                while time.time() - start_time < timeout:
                    try:
                        current_time = self.driver.execute_script(
                            "return document.querySelector('video').currentTime"
                        )

                        # 检查播放是否停滞
                        if current_time == last_time:
                            if stall_start is None:
                                stall_start = time.time()
                            elif time.time() - stall_start > 10:  # 停滞超过10秒
                                raise Exception("视频播放停滞")
                        else:
                            stall_start = None
                            last_time = current_time

                        # 检查是否达到观看时长
                        if current_time >= duration:
                            logger.info(f"成功观看视频 {url} {duration}秒")
                            return True

                    except Exception as e:
                        logger.warning(f"监控播放进度时出错: {str(e)}")

                    time.sleep(1)

            except Exception as e:
                logger.error(f"观看视频失败 ({url}): {str(e)}")
                if not self.ensure_session_valid():
                    logger.warning("会话失效，将重试")
                    continue
                if attempt < max_retries - 1:
                    time.sleep(random.uniform(3, 5))
                continue

            finally:
                try:
                    self.driver.execute_script("document.querySelector('video').pause()")
                    self.get("https://www.bilibili.com")
                except:
                    pass

        return False

    def close(self):
        """关闭浏览器实例"""
        try:
            if self.driver:
                self.driver.quit()
        except Exception as e:
            logger.error(f"关闭浏览器失败: {str(e)}")


class PreTrainManager:
    def __init__(self, browser_manager):
        self.browser_manager = browser_manager
        self.training_lock = Lock()
        self.batch_completion_count = 0
        self.batch_completion_lock = Lock()
        self.batch_event = threading.Event()
        self.progress_tracker = defaultdict(dict)
        self.global_rest_time = None
        self.invalid_videos = set()  # 用于记录无效视频
        self.invalid_videos_lock = Lock()

    def mark_video_invalid(self, video_url):
        """标记视频为无效"""
        with self.invalid_videos_lock:
            self.invalid_videos.add(video_url)
            logger.warning(f"视频已标记为无效: {video_url}")

    def is_video_invalid(self, video_url):
        """检查视频是否已被标记为无效"""
        with self.invalid_videos_lock:
            return video_url in self.invalid_videos

    def pretrain_group(self, accounts, experiment_manager, videos_per_user, videos_per_group, video_duration):
        """并行预训练一组账户"""
        try:
            # 记录每个组别的账户数量
            group_stats = defaultdict(int)
            for acc in accounts:
                group_stats[acc['group']] += 1
            logger.info(f"开始并行预训练: {dict(group_stats)}")

            # 为每个账户分配视频池
            for account in accounts:
                if account['group'] == 'state':
                    available_videos = experiment_manager.state_videos[:]
                elif account['group'] == 'non-state':
                    available_videos = experiment_manager.non_state_videos[:]
                else:
                    continue

                account['video_pool'] = available_videos
                account['current_batch_success'] = 0

            accounts_per_batch = len([acc for acc in accounts if acc['group'] != 'control'])

            def train_account(account, batch_event):
                try:
                    if account['group'] == 'control':
                        return True

                    logger.info(f"开始训练账户 {account['username']} ({account['group']})")
                    driver = self.browser_manager.get_driver(account['username'])

                    if not driver:
                        logger.error(f"无法获取账户 {account['username']} 的浏览器实例")
                        return False

                    total_batches = videos_per_user // videos_per_group

                    for batch_num in range(total_batches):
                        account['current_batch_success'] = 0
                        watched_videos = set()

                        logger.info(f"账户 {account['username']} 开始观看第 {batch_num + 1}/{total_batches} 组视频")

                        while account['current_batch_success'] < videos_per_group:
                            # 从视频池中选择未观看且未被标记为无效的视频
                            available_videos = [v for v in account['video_pool']
                                                if v not in watched_videos and not self.is_video_invalid(v)]

                            if not available_videos:
                                logger.error(f"账户 {account['username']} 视频池耗尽")
                                return False

                            video_url = random.choice(available_videos)
                            watched_videos.add(video_url)

                            try:
                                watch_result = driver.watch_video(video_url, duration=video_duration)

                                if watch_result is None:  # 视频确认不可用
                                    self.mark_video_invalid(video_url)
                                    continue

                                if watch_result:  # 成功观看
                                    account['current_batch_success'] += 1
                                    account['completed_videos_count'] += 1

                                    watch_record = {
                                        'url': video_url,
                                        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                                        'duration': video_duration,
                                        'batch_number': batch_num + 1,
                                        'batch_video_number': account['current_batch_success'],
                                        'success': True
                                    }
                                    account['watched_videos'].append(watch_record)

                                    logger.info(
                                        f"账户 {account['username']} 在第 {batch_num + 1} 组完成第 {account['current_batch_success']}/10 个视频")
                                else:
                                    logger.warning(f"账户 {account['username']} 视频 {video_url} 观看失败，将尝试新视频")
                            except Exception as e:
                                logger.error(f"观看视频失败 ({account['username']}): {str(e)}")
                                continue

                        # 本组10个视频全部观看完成，等待其他账户
                        logger.info(f"账户 {account['username']} 完成第 {batch_num + 1} 组全部10个视频")

                        with self.batch_completion_lock:
                            self.batch_completion_count += 1
                            logger.info(
                                f"账户 {account['username']} 完成第 {batch_num + 1} 组，等待其他账户... ({self.batch_completion_count}/{accounts_per_batch})")

                            if self.batch_completion_count == accounts_per_batch:
                                if batch_num < total_batches - 1:
                                    self.global_rest_time = random.uniform(300, 600)
                                    logger.info(
                                        f"\n=== 第 {batch_num + 1} 组全部完成，统一休息 {self.global_rest_time / 60:.1f} 分钟 ===")
                                batch_event.set()
                                self.batch_completion_count = 0

                        # 等待该批次所有账户完成
                        batch_event.wait()

                        # 统一休息时间
                        if batch_num < total_batches - 1:
                            time.sleep(self.global_rest_time)

                        # 重置事件，准备下一组
                        if self.batch_completion_count == 0:
                            batch_event.clear()

                    return True

                except Exception as e:
                    logger.error(f"训练账户失败 ({account['username']}): {str(e)}")
                    return False

            # 并行执行训练
            batch_event = threading.Event()
            with concurrent.futures.ThreadPoolExecutor(max_workers=len(accounts)) as executor:
                futures = {executor.submit(train_account, account, batch_event): account
                           for account in accounts if account['group'] != 'control'}

                for future in concurrent.futures.as_completed(futures):
                    account = futures[future]
                    try:
                        success = future.result()
                        if not success:
                            logger.error(f"账户 {account['username']} 训练失败")
                    except Exception as e:
                        logger.error(f"处理账户 {account['username']} 时发生错误: {str(e)}")

            # 实验结束后，保存无效视频列表
            if self.invalid_videos:
                try:
                    invalid_videos_path = os.path.join(DIRS['results'], 'invalid_videos.json')
                    with open(invalid_videos_path, 'w', encoding='utf-8') as f:
                        json.dump(list(self.invalid_videos), f, indent=2, ensure_ascii=False)
                    logger.info(f"已保存 {len(self.invalid_videos)} 个无效视频记录")
                except Exception as e:
                    logger.error(f"保存无效视频记录失败: {str(e)}")

            return accounts

        except Exception as e:
            logger.error(f"预训练过程失败: {str(e)}")
            self._handle_training_failure(accounts, e)
            raise

class ExperimentManager:
    def __init__(self):
        try:
            self.state_videos_csv = f"{BASE_DIR}/state.csv"
            self.non_state_videos_csv = f"{BASE_DIR}/non.csv"

            if not os.path.exists(self.state_videos_csv):
                raise FileNotFoundError(f"找不到state视频文件: {self.state_videos_csv}")
            if not os.path.exists(self.non_state_videos_csv):
                raise FileNotFoundError(f"找不到non-state视频文件: {self.non_state_videos_csv}")

            try:
                self.state_videos = pd.read_csv(self.state_videos_csv)['视频链接'].tolist()
            except UnicodeDecodeError:
                self.state_videos = pd.read_csv(self.state_videos_csv, encoding='gbk')['视频链接'].tolist()

            try:
                self.non_state_videos = pd.read_csv(self.non_state_videos_csv)['视频链接'].tolist()
            except UnicodeDecodeError:
                self.non_state_videos = pd.read_csv(self.non_state_videos_csv, encoding='gbk')['视频链接'].tolist()

            self.state_videos = [url for url in self.state_videos if validate_video_url(url)]
            self.non_state_videos = [url for url in self.non_state_videos if validate_video_url(url)]

            if not self.state_videos:
                raise ValueError("未找到有效的state视频链接")
            if not self.non_state_videos:
                raise ValueError("未找到有效的non-state视频链接")

            self.api = BilibiliAPI()
            self.browser_manager = BrowserManager()  # 在这里初始化
            self.log_lock = Lock()
            self.results_lock = Lock()
            self.checkpoint_lock = Lock()

            logger.info(
                f"已加载 {len(self.state_videos)} 个state视频和 {len(self.non_state_videos)} 个non-state视频")

        except Exception as e:
            logger.error(f"初始化视频池失败: {str(e)}")
            raise

    def collect_data_parallel(self, accounts, max_workers=None):
        """并行收集数据，确保每组数据完整性"""
        shared_results = []
        max_workers = min(len(accounts), 10)

        # 按组跟踪进度
        group_progress = {
            'state': {'required': 5, 'completed': 0, 'accounts': []},
            'non-state': {'required': 5, 'completed': 0, 'accounts': []},
            'control': {'required': 5, 'completed': 0, 'accounts': []}
        }

        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
                while not self._all_groups_completed(group_progress):
                    incomplete_accounts = self._get_incomplete_accounts(accounts, group_progress)

                    if not incomplete_accounts:
                        break

                    futures = {
                        executor.submit(self.collect_data_for_user, account): account
                        for account in incomplete_accounts
                    }

                    for future in concurrent.futures.as_completed(futures):
                        account = futures[future]
                        try:
                            results = future.result(timeout=300)  # 5分钟超时
                            if self._verify_account_data(results, account):
                                with self.results_lock:
                                    shared_results.extend(results)
                                    self._update_group_progress(account, group_progress)
                            else:
                                logger.warning(f"账号 {account['username']} 数据不完整，将重试")
                        except Exception as e:
                            logger.error(f"处理账号 {account['username']} 失败: {str(e)}")
                            if self._should_create_new_account(account, group_progress):
                                new_account = self._create_replacement_account(account['group'])
                                if new_account:
                                    accounts.append(new_account)

            # 验证最终结果
            if not self._verify_final_results(shared_results, group_progress):
                raise Exception("数据收集未达到要求")

            # 保存结果
            self.save_collected_videos(shared_results)
            return shared_results

        except Exception as e:
            logger.error(f"并行数据收集过程出错: {str(e)}")
            raise

    def collect_data_for_user(self, account):
        """改进的单用户数据收集方法"""
        max_retries = 5
        retry_count = 0
        local_results = []

        while retry_count < max_retries:
            try:
                # 1. 获取或重新创建浏览器实例
                driver = self.browser_manager.get_driver(account['username'])
                if not driver or not driver.ensure_session_valid():
                    logger.warning(f"用户 {account['username']} 的浏览器实例无效，重新创建...")
                    # 确保完全关闭旧实例
                    if driver:
                        try:
                            driver.close()
                        except:
                            pass
                    time.sleep(random.uniform(2, 5))
                    driver = self.create_new_browser_instance(account['username'])
                    if not driver:
                        raise Exception("无法创建新的浏览器实例")

                # 2. 访问首页进行预热
                if not driver.get("https://www.bilibili.com"):
                    raise Exception("无法访问首页")

                # 3. 等待页面加载
                time.sleep(random.uniform(3, 5))

                # 4. 执行一些人类行为模拟
                self._simulate_human_behavior(driver)

                # 5. 获取新cookie
                new_cookies = self.refresh_cookies(driver, account['username'])
                if not new_cookies:
                    raise Exception("无法获取有效cookie")

                # 6. 获取首页视频
                homepage_videos = self.get_homepage_videos_with_retry(account['username'], new_cookies)

                if homepage_videos:
                    logger.info(f"用户 {account['username']} 成功获取 {len(homepage_videos)} 个首页视频")

                    # 处理视频数据
                    for video in homepage_videos:
                        try:
                            video_data = self._process_video_data(video, account)
                            if video_data:
                                local_results.append(video_data)

                                # 获取相关视频
                                related_videos = self._get_related_videos_safely(video, account)
                                if related_videos:
                                    local_results.extend(related_videos)

                                # 每处理完一个视频就检查数据完整性
                                if self._verify_partial_data(local_results):
                                    return local_results

                        except Exception as e:
                            logger.error(f"处理视频数据时出错 ({account['username']}): {str(e)}")
                            continue

                # 如果数据不完整，增加重试计数
                retry_count += 1
                if retry_count < max_retries:
                    # 使用指数退避策略
                    wait_time = min(2 ** retry_count * 5, 120)  # 最多等待2分钟
                    logger.warning(f"用户 {account['username']} 第 {retry_count} 次尝试失败，等待 {wait_time} 秒...")
                    time.sleep(wait_time)

                    # 在重试前清除session
                    self.api.session.cookies.clear()

            except Exception as e:
                logger.error(f"收集数据失败 ({account['username']}): {str(e)}")
                retry_count += 1
                if retry_count < max_retries:
                    time.sleep(random.uniform(10, 20))
                continue

        return local_results

    def _simulate_human_behavior(self, driver):
        """模拟人类行为"""
        try:
            # 随机滚动
            driver.driver.execute_script(f"window.scrollTo(0, {random.randint(100, 500)});")
            time.sleep(random.uniform(1, 2))

            # 随机移动鼠标
            actions = ActionChains(driver.driver)
            elements = driver.driver.find_elements(By.CSS_SELECTOR, 'a, button, input')
            if elements:
                random_element = random.choice(elements)
                actions.move_to_element(random_element).perform()

            time.sleep(random.uniform(1, 2))

        except Exception as e:
            logger.warning(f"模拟人类行为时出错: {str(e)}")

    def _verify_partial_data(self, results):
        """验证部分数据是否已经足够"""
        if not results:
            return False

        homepage_count = len([r for r in results if r['source'] == 'homepage'])
        related_count = len([r for r in results if r['source'] == 'related'])

        # 如果已经获取了足够的数据，就可以提前返回
        return homepage_count >= 27 and related_count >= 270  # 允许90%的完整度

    def _update_group_progress(self, account, group_progress):
        """更新组进度"""
        group = account['group']
        if group in group_progress:
            if account['username'] not in group_progress[group]['accounts']:
                group_progress[group]['completed'] += 1
                group_progress[group]['accounts'].append(account['username'])
                logger.info(f"{group}组进度: {group_progress[group]['completed']}/{group_progress[group]['required']}")

    def _all_groups_completed(self, group_progress):
        """检查是否所有组都完成"""
        return all(
            stats['completed'] >= stats['required']
            for stats in group_progress.values()
        )

    def _get_incomplete_accounts(self, accounts, group_progress):
        """获取未完成的账号列表"""
        return [
            account for account in accounts
            if account['group'] in group_progress
               and account['username'] not in group_progress[account['group']]['accounts']
               and group_progress[account['group']]['completed'] < group_progress[account['group']]['required']
        ]

    def _should_create_new_account(self, account, group_progress):
        """决定是否需要创建新账号"""
        group = account['group']
        failure_threshold = 3  # 允许的失败次数
        current_accounts = len([a for a in group_progress[group]['accounts']])
        return (current_accounts < group_progress[group]['required'] * 2 and
                group_progress[group]['completed'] < group_progress[group]['required'])

    def _create_replacement_account(self, group):
        """创建替代账号"""
        try:
            username = generate_username()
            driver = BilibiliDriver()

            if not driver.get("https://www.bilibili.com"):
                return None

            cookies = driver.driver.get_cookies()
            if not cookies:
                return None

            save_cookies(username, cookies)

            account = {
                'username': username,
                'sex': random.choice(['male', 'female']),
                'group': group,
                'watched_videos': [],
                'completed_videos_count': 0
            }

            # 保存浏览器实例
            self.browser_manager.browsers[username] = driver

            return account

        except Exception as e:
            logger.error(f"创建替代账号失败: {str(e)}")
            return None

    def refresh_cookies(self, driver, username, max_cookie_retries=3):
        """刷新cookie"""
        for attempt in range(max_cookie_retries):
            try:
                if driver.get("https://www.bilibili.com"):
                    time.sleep(5 + attempt * 2)

                    try:
                        WebDriverWait(driver.driver, 10).until(
                            EC.presence_of_element_located((By.CSS_SELECTOR, ".bili-feed4"))
                        )
                    except Exception as e:
                        logger.warning(f"等待页面元素超时 ({username}): {str(e)}")

                    new_cookies = driver.driver.get_cookies()
                    if new_cookies and self._verify_cookies(new_cookies):
                        self._save_new_cookies(username, new_cookies)
                        return new_cookies

                logger.warning(f"第 {attempt + 1} 次获取cookie失败，重试...")
                time.sleep(random.uniform(3, 5))

            except Exception as e:
                logger.error(f"刷新cookie失败 ({username}): {str(e)}")
                time.sleep(random.uniform(3, 5))

        return None

    def _verify_cookies(self, cookies):
        """验证cookie有效性"""
        if not cookies:
            return False

        required_domains = ['bilibili.com', '.bilibili.com']
        required_cookies = ['buvid3', 'b_nut']

        domains_found = any(cookie.get('domain') in required_domains for cookie in cookies)
        cookies_found = any(cookie.get('name') in required_cookies for cookie in cookies)

        return domains_found and cookies_found

    def _save_new_cookies(self, username, cookies):
        """保存新cookie"""
        try:
            new_cookie_path = os.path.join(DIRS['cookies'], f"{username}_new.json")
            with open(new_cookie_path, 'w', encoding='utf-8') as f:
                json.dump(cookies, f, ensure_ascii=False)
            logger.info(f"成功获取新cookie: {username}")
        except Exception as e:
            logger.error(f"保存新cookie失败 ({username}): {str(e)}")

    def get_homepage_videos_with_retry(self, username, cookies, max_retries=5):
        """获取首页视频（带重试）"""
        self.api.set_cookies(cookies)

        for attempt in range(max_retries):
            try:
                videos = self.api.get_homepage_videos()  # 不需要传入 username
                if videos:
                    return videos

                wait_time = min(2 ** attempt * 5, 60)
                if attempt < max_retries - 1:
                    logger.warning(f"用户 {username} 第 {attempt + 1} 次获取首页视频为空，等待 {wait_time} 秒...")
                    time.sleep(wait_time)

                    # 在重试前刷新cookie
                    if attempt > 1:  # 从第三次开始刷新cookie
                        driver = self.browser_manager.get_driver(username)
                        if driver:
                            new_cookies = self.refresh_cookies(driver, username)
                            if new_cookies:
                                self.api.set_cookies(new_cookies)

            except Exception as e:
                logger.error(f"获取首页视频失败 ({username}): {str(e)}")
                if attempt < max_retries - 1:
                    time.sleep(random.uniform(5, 10))

        return None

    def _verify_final_results(self, shared_results, group_progress):
        """验证最终结果是否满足要求"""
        if not shared_results:
            return False

        # 按组统计数据
        group_counts = defaultdict(int)
        for result in shared_results:
            group_counts[result['group']] += 1

        # 验证每个组是否都达到最小要求
        min_required_per_account = 330  # 30个首页视频 * (1 + 10个相关推荐)
        for group, stats in group_progress.items():
            required_count = stats['required'] * min_required_per_account * 0.9  # 允许10%的误差
            if group_counts[group] < required_count:
                logger.error(f"{group}组数据不完整: 获取{group_counts[group]}条，需要{required_count}条")
                return False

        return True

    def save_collected_videos(self, collected_data):
        """按组别分别保存采集的视频数据到CSV文件"""
        try:
            # 按组别分类数据
            grouped_data = {
                'state': [],
                'non-state': [],
                'control': []
            }

            for data in collected_data:
                group = data['group'].lower()
                if group in grouped_data:
                    grouped_data[group].append(data)

            # 为每个组别创建CSV文件
            timestamp = int(time.time())
            headers = [
                'username',  # 用户名
                'group',  # 组别(state/non-state/control)
                'video_type',  # homepage/recommended
                'video_url',  # 视频链接
                'video_title',  # 视频标题
                'author',  # 作者
                'source_video_bvid',  # 如果是推荐视频，这个是来源视频的bvid
                'timestamp'  # 采集时间
            ]

            for group, data in grouped_data.items():
                if not data:  # 如果该组没有数据，跳过
                    continue

                group_path = f"{DIRS['results']}/{group}_videos_{timestamp}.csv"
                temp_path = f"{group_path}.tmp"

                try:
                    with open(temp_path, 'w', newline='', encoding='utf-8-sig') as f:
                        writer = csv.writer(f)
                        writer.writerow(headers)

                        for item in data:
                            writer.writerow([
                                item['username'],
                                item['group'],
                                item['source'],
                                item.get('video_url', ''),
                                item.get('video_title', ''),
                                item.get('author', ''),
                                item.get('from_video_bvid', ''),
                                item.get('timestamp', '')
                            ])

                    # 完成写入后重命名文件
                    os.replace(temp_path, group_path)
                    logger.info(f"{group}组视频数据已保存至: {group_path} (共{len(data)}条记录)")

                except Exception as e:
                    logger.error(f"保存{group}组数据时出错: {str(e)}")
                    # 清理临时文件
                    if os.path.exists(temp_path):
                        try:
                            os.remove(temp_path)
                        except:
                            pass

            # 记录总体统计信息
            total_records = sum(len(data) for data in grouped_data.values())
            group_stats = {group: len(data) for group, data in grouped_data.items()}
            logger.info(f"所有数据保存完成，总记录数: {total_records}")
            logger.info(f"各组记录数: {group_stats}")

        except Exception as e:
            logger.error(f"保存视频数据失败: {str(e)}")
            raise

    def create_new_browser_instance(self, username):
        """创建新的浏览器实例"""
        try:
            driver = BilibiliDriver()
            if not driver.get("https://www.bilibili.com"):
                return None

            self.browser_manager.browsers[username] = driver
            return driver
        except Exception as e:
            logger.error(f"创建新浏览器实例失败 ({username}): {str(e)}")
            return None

    def _process_video_data(self, video, account):
        """处理单个视频数据"""
        try:
            return {
                'username': account['username'],
                'group': account['group'],
                'source': 'homepage',
                'video_url': video.get('uri', ''),
                'video_title': video.get('title', ''),
                'author': video.get('owner', {}).get('name', ''),
                'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }
        except Exception as e:
            logger.error(f"处理视频数据失败: {str(e)}")
            return None

    def _get_related_videos_safely(self, video, account):
        """安全地获取相关视频"""
        try:
            bvid = video.get('uri', '').split('/')[-1] if 'BV' in video.get('uri', '') else None
            if not bvid:
                return []

            time.sleep(random.uniform(1, 2))  # 随机延迟

            related_videos = []
            related_data = self.api.get_related_videos(bvid)

            for idx, related in enumerate(related_data, 1):
                try:
                    related_info = {
                        'username': account['username'],
                        'group': account['group'],
                        'source': 'related',
                        'video_url': f"https://www.bilibili.com/video/{related.get('bvid')}",
                        'video_title': related.get('title', ''),
                        'author': related.get('owner', {}).get('name', ''),
                        'main_video_url': video.get('uri', ''),
                        'main_video_title': video.get('title', ''),
                        'relation_order': idx,
                        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    }
                    related_videos.append(related_info)

                    # 如果已经收集了足够的相关视频，提前返回
                    if len(related_videos) >= 10:
                        break

                except Exception as e:
                    logger.warning(f"处理相关视频数据出错: {str(e)}")
                    continue

                # 在每个相关视频处理之间添加短暂延迟
                time.sleep(random.uniform(0.5, 1))

            return related_videos

        except Exception as e:
            logger.error(f"获取相关视频失败: {str(e)}")
            return []

    def save_watch_history(self, accounts):
        """保存观看历史记录"""
        try:
            timestamp = int(time.time())
            history_path = os.path.join(DIRS['results'], f'watch_history_{timestamp}.json')

            # 过滤掉不需要的字段，只保存关键信息
            filtered_accounts = []
            for account in accounts:
                filtered_account = {
                    'username': account['username'],
                    'group': account['group'],
                    'completed_videos_count': account.get('completed_videos_count', 0),
                    'watched_videos': account.get('watched_videos', [])
                }
                filtered_accounts.append(filtered_account)

            with open(history_path, 'w', encoding='utf-8') as f:
                json.dump(filtered_accounts, f, ensure_ascii=False, indent=2)

            logger.info(f"已保存观看历史记录: {history_path}")

        except Exception as e:
            logger.error(f"保存观看历史记录失败: {str(e)}")

    def save_checkpoint(self, accounts, round_number, results):
        """保存实验检查点"""
        try:
            checkpoint_data = {
                'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'round_number': round_number,
                'accounts': accounts,
                'results': results
            }

            checkpoint_path = os.path.join(DIRS['checkpoints'], f'checkpoint_{round_number}_{int(time.time())}.json')

            with open(checkpoint_path, 'w', encoding='utf-8') as f:
                json.dump(checkpoint_data, f, ensure_ascii=False, indent=2)

            logger.info(f"已保存第 {round_number} 轮检查点: {checkpoint_path}")

        except Exception as e:
            logger.error(f"保存检查点失败: {str(e)}")

    def collect_data_parallel_for_account(self, account):
        """为单个账号并行收集数据，针对5并发优化"""
        max_retries = 8  # 增加最大重试次数
        base_wait_time = 10  # 基础等待时间

        try:
            retries = 0
            while retries < max_retries:
                try:
                    # 在每次尝试前添加随机延迟
                    delay = random.uniform(base_wait_time + retries * 2,
                                           base_wait_time + retries * 5)
                    time.sleep(delay)

                    # 获取数据
                    results = self.collect_data_for_user(account)

                    if results:
                        # 验证数据完整性
                        homepage_count = len([r for r in results if r['source'] == 'homepage'])
                        related_count = len([r for r in results if r['source'] == 'related'])

                        if homepage_count >= 27 and related_count >= 270:  # 90%完整度
                            logger.info(
                                f"账号 {account['username']} ({account['group']}) 成功收集 {len(results)} 条数据")
                            return results
                        else:
                            logger.warning(
                                f"账号 {account['username']} 数据不完整: 首页={homepage_count}, 相关={related_count}")

                    # 增加重试计数
                    retries += 1
                    if retries < max_retries:
                        # 使用指数退避
                        wait_time = min(2 ** retries * base_wait_time, 300)  # 最多等待5分钟
                        logger.warning(f"账号 {account['username']} 重试 {retries}/{max_retries}, 等待 {wait_time}秒")
                        time.sleep(wait_time)

                        # 清理之前的会话
                        self.api.session.cookies.clear()

                except Exception as e:
                    logger.error(f"账号 {account['username']} 单次尝试失败: {str(e)}")
                    retries += 1
                    if retries < max_retries:
                        time.sleep(random.uniform(20, 40))
                    continue

            logger.error(f"账号 {account['username']} 重试耗尽，放弃该账号")
            return []

        except Exception as e:
            logger.error(f"账号 {account['username']} 数据收集完全失败: {str(e)}")
            return []

def init_account_cookies():
    """初始化账户cookies"""
    try:
        driver = BilibiliDriver()
        if driver.get("https://www.bilibili.com"):
            time.sleep(2)
            cookies = driver.driver.get_cookies()
            if cookies:
                for cookie in cookies:
                    if not all(k in cookie for k in ['name', 'value', 'domain']):
                        logger.error(f"Cookie格式不完整: {cookie}")
                        return None
                    if not cookie['domain'].endswith('bilibili.com'):
                        logger.error(f"无效的cookie domain: {cookie['domain']}")
                        return None
            return cookies if cookies else None
        return None
    except Exception as e:
        logger.error(f"初始化cookies失败: {str(e)}")
        return None


def validate_video_url(url: str) -> bool:
    """验证B站视频URL格式"""
    if not url:
        return False
    if not url.startswith('https://www.bilibili.com/video/'):
        return False
    if len(url.split('/')) < 5:
        return False
    return True


def generate_username():
    """生成随机用户名"""
    return ''.join(random.choices(string.ascii_letters + string.digits, k=8))


def save_cookies(username, cookies):
    """保存账户的cookies"""
    try:
        cookie_path = os.path.join(DIRS['cookies'], f"{username}.json")
        with open(cookie_path, 'w', encoding='utf-8') as f:
            json.dump(cookies, f, ensure_ascii=False)
        logger.info(f"Cookies已保存: {username}")
    except Exception as e:
        logger.error(f"保存Cookies失败 ({username}): {str(e)}")


def load_cookies(username):
    """加载账户的cookies，优先使用新cookie"""
    try:
        # 先尝试加载新cookie
        new_cookie_path = os.path.join(DIRS['cookies'], f"{username}_new.json")
        if os.path.exists(new_cookie_path):
            with open(new_cookie_path, 'r', encoding='utf-8') as f:
                cookies = json.load(f)
            logger.info(f"已加载新Cookies: {username}_new.json")
            return cookies

        # 如果没有新cookie，加载旧cookie
        old_cookie_path = os.path.join(DIRS['cookies'], f"{username}.json")
        if os.path.exists(old_cookie_path):
            with open(old_cookie_path, 'r', encoding='utf-8') as f:
                cookies = json.load(f)
            logger.info(f"已加载旧Cookies: {username}.json")
            return cookies
        return None
    except Exception as e:
        logger.error(f"加载Cookies失败 ({username}): {str(e)}")
        return None


def create_virtual_accounts(num_accounts: int, group_type: str, browser_manager):
    """创建虚拟账户"""
    accounts = []
    attempt = 0

    while len(accounts) < num_accounts:
        attempt += 1
        try:
            username = generate_username()
            driver = BilibiliDriver()

            if not driver.get("https://www.bilibili.com"):
                logger.warning(f"第 {attempt} 次尝试: 访问B站失败，将重试")
                continue

            cookies = driver.driver.get_cookies()
            if not cookies:
                logger.warning(f"第 {attempt} 次尝试: 获取cookies失败，将重试")
                continue

            save_cookies(username, cookies)
            loaded_cookies = load_cookies(username)

            if not loaded_cookies:
                logger.warning(f"第 {attempt} 次尝试: cookies保存或加载失败，将重试")
                continue

            # 保存浏览器实例
            browser_manager.browsers[username] = driver

            account = {
                'username': username,
                'sex': random.choice(['male', 'female']),
                'group': group_type.strip().lower(),
                'watched_videos': [],
                'completed_videos_count': 0
            }
            accounts.append(account)
            logger.info(
                f"第 {attempt} 次尝试: 成功创建用户 {username}, 组别: {group_type}, 进度: {len(accounts)}/{num_accounts}")

        except Exception as e:
            logger.error(f"第 {attempt} 次尝试: 创建账户失败: {str(e)}")
            continue

    logger.info(f"完成 {group_type} 组账户创建，共尝试 {attempt} 次，成功创建 {len(accounts)} 个账户")
    return accounts


def run_batch_experiment(round_number, total_rounds, concurrent_users_per_group, videos_per_user, videos_per_group,
                         video_duration):
    max_retries = 3  # 定义最大重试次数

    try:
        logger.info(f"\n{'=' * 20} 开始第 {round_number}/{total_rounds} 轮 {'=' * 20}")

        batch_manager = BatchManager()
        browser_manager = BrowserManager()
        experiment_manager = ExperimentManager()
        experiment_manager.browser_manager = browser_manager
        pretrain_manager = PreTrainManager(browser_manager)

        # 创建训练账户
        training_accounts = None
        for attempt in range(max_retries):
            try:
                # 清理之前批次的实例(如果有)
                browser_manager.cleanup_all_browsers()
                gc.collect()
                time.sleep(5)

                training_accounts = browser_manager.create_all_browsers(
                    concurrent_users_per_group,
                    groups=['state', 'non-state']
                )

                if training_accounts:
                    break
            except Exception as e:
                if attempt == max_retries - 1:
                    raise Exception(f"创建训练账户失败，已重试{max_retries}次: {str(e)}")
                logger.error(f"创建训练账户失败，尝试 {attempt + 1}/{max_retries}: {str(e)}")
                time.sleep(random.uniform(30, 60))

        if not training_accounts:
            raise Exception("无法创建训练账户")

        # 训练阶段
        trained_accounts = pretrain_manager.pretrain_group(
            training_accounts,
            experiment_manager,
            videos_per_user,
            videos_per_group,
            video_duration
        )

        # 训练后休息但保持浏览器实例运行
        rest_time = random.uniform(30, 60)  # 5-10分钟
        logger.info(f"\n=== 训练阶段完成，休息 {rest_time / 60:.1f} 分钟 ===")
        time.sleep(rest_time)

        # 为对照组创建新的浏览器实例,不影响已训练的实例
        control_accounts = browser_manager.create_all_browsers(
            concurrent_users_per_group,
            groups=['control'],
            cleanup_existing=False  # 添加这个参数
        )

        if not control_accounts:
            raise Exception("无法创建对照组账户")

        # 合并所有账号准备收集数据
        all_accounts = training_accounts + control_accounts

        # 收集数据时使用现有的浏览器实例
        results = experiment_manager.collect_data_parallel(all_accounts)

        # 保存数据
        experiment_manager.save_watch_history(all_accounts)
        experiment_manager.save_checkpoint(all_accounts, round_number, results)

        # 批次完全完成后才清理
        browser_manager.cleanup_all_browsers()
        gc.collect()

        return results

    except Exception as e:
        logger.error(f"第 {round_number} 轮执行失败: {str(e)}")
        # 发生错误时也需要清理
        browser_manager.cleanup_all_browsers()
        gc.collect()
        raise



def main():
    # 实验参数设置
    TOTAL_USERS_PER_GROUP = 20  # 每组总用户数
    CONCURRENT_USERS_PER_GROUP = 5  # 每组并发用户数保持5，请保持不变
    VIDEOS_PER_USER = 10  # 每个用户要观看的视频总数
    VIDEOS_PER_GROUP = 10  # 每组视频数 * 正式测试请改成10
    VIDEO_DURATION = 1  # 每个视频观看时长（秒）* 正式测试请改成30
    MIN_BATCH_INTERVAL = 28  # 批次间最小间隔（分钟）
    MAX_BATCH_INTERVAL = 33  # 批次间最大间隔（分钟）

    try:
        # 验证参数
        if VIDEOS_PER_USER % VIDEOS_PER_GROUP != 0:
            raise ValueError(f"每用户视频数({VIDEOS_PER_USER})必须是每组视频数({VIDEOS_PER_GROUP})的整数倍")
        if TOTAL_USERS_PER_GROUP % CONCURRENT_USERS_PER_GROUP != 0:
            raise ValueError(
                f"每组总用户数({TOTAL_USERS_PER_GROUP})必须是并发用户数({CONCURRENT_USERS_PER_GROUP})的整数倍")

        # 清理目录
        DirectoryManager.clean_directories()
        DirectoryManager.ensure_directories()

        # 初始化管理器
        resource_manager = ResourceManager()
        experiment_monitor = ExperimentMonitor()
        experiment_monitor.start_experiment()
        browser_manager = BrowserManager()

        # 计算需要执行的总轮次
        total_rounds = TOTAL_USERS_PER_GROUP // CONCURRENT_USERS_PER_GROUP

        logger.info("\n" + "=" * 50)
        logger.info("开始大规模实验...")
        logger.info(f"每组总用户数: {TOTAL_USERS_PER_GROUP}")
        logger.info(f"每组并发用户数: {CONCURRENT_USERS_PER_GROUP}")
        logger.info(f"总轮次数: {total_rounds}")
        logger.info(f"每轮并发总人数: {CONCURRENT_USERS_PER_GROUP * 3}")
        logger.info(f"每用户视频数: {VIDEOS_PER_USER}")
        logger.info(f"每组视频数: {VIDEOS_PER_GROUP}")
        logger.info(f"视频观看时长: {VIDEO_DURATION}秒")
        logger.info(f"轮次间隔: {MIN_BATCH_INTERVAL}-{MAX_BATCH_INTERVAL}分钟")
        logger.info("=" * 50)

        batch_manager = BatchManager()
        all_results = []
        round_success_count = 0

        for round_num in range(1, total_rounds + 1):
            try:
                # 检查和清理资源
                memory_before = psutil.Process().memory_percent()
                logger.info(f"当前轮次开始前内存使用率: {memory_before:.1f}%")

                # 强制清理
                browser_manager.cleanup_all_browsers()
                gc.collect()

                # 检查清理效果
                memory_after = psutil.Process().memory_percent()
                logger.info(f"清理后内存使用率: {memory_after:.1f}%")

                if memory_after > 80:
                    logger.warning(f"内存使用率仍然过高，等待系统回收...")
                    time.sleep(180)  # 等待3分钟
                    gc.collect()

                logger.info(f"\n{'=' * 20} 开始第 {round_num}/{total_rounds} 轮 {'=' * 20}")

                # 记录本轮开始时间
                round_start_time = time.time()

                # 运行本轮实验
                try:
                    round_results = run_batch_experiment(
                        round_num,
                        total_rounds,
                        CONCURRENT_USERS_PER_GROUP,
                        VIDEOS_PER_USER,
                        VIDEOS_PER_GROUP,
                        VIDEO_DURATION
                    )
                except Exception as e:
                    logger.error(f"第 {round_num} 轮执行失败: {str(e)}")
                    # 发生错误时也要确保清理
                    browser_manager.cleanup_all_browsers()
                    gc.collect()
                    # 短暂休息后继续下一轮
                    time.sleep(300)  # 5分钟
                    continue

                # 更新统计
                if round_results:
                    all_results.extend(round_results)
                    round_success_count += 1

                experiment_monitor.update_stats(
                    total_accounts=CONCURRENT_USERS_PER_GROUP * 3,
                    successful_accounts=len(round_results) if round_results else 0,
                    failed_accounts=CONCURRENT_USERS_PER_GROUP * 3 - (len(round_results) if round_results else 0)
                )

                # 计算本轮用时
                round_duration = time.time() - round_start_time
                logger.info(f"第 {round_num} 轮用时: {round_duration / 60:.1f} 分钟")

                # 确保间隔时间合理
                if round_num < total_rounds:
                    # 根据本轮用时动态调整休息时间
                    min_rest = max(MIN_BATCH_INTERVAL * 60, round_duration * 0.5)  # 至少休息本轮用时的一半
                    max_rest = max(MAX_BATCH_INTERVAL * 60, round_duration)  # 最多休息本轮用时那么久
                    rest_time = random.uniform(min_rest, max_rest)

                    logger.info(f"\n=== 第 {round_num} 轮完成，休息 {rest_time / 60:.1f} 分钟后开始下一轮 ===")

                    # 分段休息，每段后检查内存
                    rest_segments = 6  # 将休息时间分成6段
                    segment_time = rest_time / rest_segments
                    for i in range(rest_segments):
                        time.sleep(segment_time)
                        memory_current = psutil.Process().memory_percent()
                        logger.info(f"休息中...({i + 1}/{rest_segments}) 当前内存使用率: {memory_current:.1f}%")
                        if memory_current > 70:
                            gc.collect()

            except Exception as e:
                logger.error(f"第 {round_num} 轮发生意外错误: {str(e)}")
                experiment_monitor.record_error("RoundError", str(e))
                time.sleep(300)  # 发生意外错误后等待5分钟
                continue

        # 清理旧文件
        resource_manager.cleanup_old_logs()
        resource_manager.cleanup_old_checkpoints()

        # 生成并保存最终报告
        final_report = experiment_monitor.generate_report()
        report_path = f"{DIRS['results']}/final_report.txt"
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write(final_report)

        logger.info("\n" + "=" * 20 + " 实验完成 " + "=" * 20)
        logger.info(f"总执行轮次: {total_rounds}")
        logger.info(f"成功轮次数: {round_success_count}")
        logger.info(f"总收集数据条数: {len(all_results)}")
        logger.info(f"最终报告已保存至: {report_path}")
        logger.info("=" * 50 + "\n")

    except Exception as e:
        logger.error(f"实验过程中出错: {str(e)}")
        experiment_monitor.record_error("ExperimentError", str(e))
        raise
    finally:
        logger.info("实验结束，保持所有浏览器窗口运行")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.warning("\n实验被用户中断")
    except Exception as e:
        logger.error(f"\n实验运行失败: {str(e)}")
    finally:
        logger.info("\n实验程序结束")

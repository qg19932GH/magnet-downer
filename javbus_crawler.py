import customtkinter as ctk
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import threading
import concurrent.futures
import csv
import re
import time
import sys
import os
import random
import io
import webbrowser
from bs4 import BeautifulSoup
from PIL import Image, ImageTk
import httpx

# Selenium imports
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException

# Set default theme
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

VIDEO_CODE_RE = re.compile(r'(?<![A-Za-z0-9])[A-Z]{2,6}-\d{3,5}(?![A-Za-z0-9])', re.IGNORECASE)
STAR_URL_RE = re.compile(r'/star/([^/?#]+)')
INVALID_CODES = {'HTTP', 'HTML', 'HTTPS', 'JAVBUS', 'SEARCH'}

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36 Edg/121.0.0.0",
]


class JavbusSeleniumCrawler:
    def __init__(self, base_url="https://www.javbus.com"):
        self.base_url = base_url.rstrip('/')
        self.results = []
        self._stop = False

    def create_driver(self, proxy=None):
        try:
            from selenium.webdriver.edge.options import Options as EdgeOptions
            EDGE_AVAILABLE = True
        except ImportError:
            EDGE_AVAILABLE = False
        from selenium.webdriver.chrome.options import Options as ChromeOptions

        browsers = []
        if EDGE_AVAILABLE:
            browsers.append((webdriver.Edge, EdgeOptions))
        browsers.append((webdriver.Chrome, ChromeOptions))

        formatted_proxy = None
        if proxy and proxy.strip():
            p = proxy.strip()
            if not p.startswith(('http://', 'https://', 'socks5://')):
                p = f"http://{p}"
            formatted_proxy = p

        for BrowserClass, OptionsClass in browsers:
            try:
                opts = OptionsClass()
                opts.page_load_strategy = 'eager'  # Eager load strategy
                opts.add_argument('--headless')
                opts.add_argument('--no-sandbox')
                opts.add_argument('--disable-gpu')
                opts.add_argument('--disable-extensions')
                opts.add_argument('--disable-blink-features=AutomationControlled')  # Anti-bot stealth
                opts.add_argument(f'user-agent={random.choice(USER_AGENTS)}')
                opts.add_argument('--log-level=3')
                opts.add_argument('--window-size=1920,1080')
                opts.add_argument('--lang=zh-CN')
                opts.add_argument('--blink-settings=imagesEnabled=false')
                opts.add_experimental_option('excludeSwitches', ['enable-logging', 'enable-automation'])

                if formatted_proxy:
                    opts.add_argument(f'--proxy-server={formatted_proxy}')

                driver = BrowserClass(options=opts)
                driver.set_page_load_timeout(20)

                # Remove navigator.webdriver flag via CDP
                try:
                    driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {
                        'source': 'Object.defineProperty(navigator, "webdriver", {get: () => undefined})'
                    })
                except Exception:
                    pass

                return driver
            except Exception:
                continue

        raise RuntimeError("无法启动 Edge 或 Chrome 浏览器。请确保已安装 Edge 或 Chrome。")

    def _pass_age_verification(self, driver):
        try:
            if "Age Verification" not in driver.title and "verify" not in driver.current_url.lower():
                return True

            try:
                checkbox = driver.find_element(By.CSS_SELECTOR, "#form1 input[type='checkbox'], input[type='checkbox']")
                if checkbox and not checkbox.is_selected():
                    checkbox.click()
                submit = driver.find_element(By.ID, "submit")
                submit.click()
                time.sleep(1.0)
                return True
            except Exception:
                pass

            return False
        except Exception:
            return False

    def stop(self):
        self._stop = True

    def get_star_page_videos(self, star_url, proxy=None, callback=None, delay=0.5):
        driver = None
        video_codes = []
        star_name = ""
        m = STAR_URL_RE.search(star_url)
        if m:
            star_name = m.group(1)

        try:
            driver = self.create_driver(proxy=proxy)
            current_url = star_url
            page_num = 1

            while not self._stop and current_url:
                if callback:
                    callback(f"正在读取第 {page_num} 页: {current_url}")

                driver.get(current_url)
                self._pass_age_verification(driver)

                # Wait for DOM ready
                time.sleep(1.0)
                page_source = driver.page_source
                soup = BeautifulSoup(page_source, 'html.parser')

                movie_boxes = soup.select('a.movie-box')
                page_codes = []
                for box in movie_boxes:
                    href = box.get('href', '')
                    code_match = re.search(r'([A-Za-z0-9-]+)$', href)
                    if code_match:
                        code = code_match.group(1).upper()
                        if code not in INVALID_CODES and '-' in code:
                            page_codes.append(code)

                if not page_codes:
                    for match in VIDEO_CODE_RE.finditer(page_source):
                        code = match.group(0).upper()
                        if code not in INVALID_CODES and len(code) > 4:
                            page_codes.append(code)

                page_codes = list(dict.fromkeys(page_codes))
                video_codes.extend(page_codes)

                if callback:
                    callback(f"第 {page_num} 页发现 {len(page_codes)} 个番号 (累计: {len(video_codes)})")

                # Find next page
                next_url = None
                next_btn = soup.select_one('a#next')
                if next_btn and next_btn.get('href'):
                    href = next_btn.get('href')
                    if href.startswith('http'):
                        next_url = href
                    else:
                        next_url = f"{self.base_url}{href}"
                elif star_name:
                    next_page_num = page_num + 1
                    possible_href = f"/star/{star_name}/{next_page_num}"
                    if possible_href in page_source:
                        next_url = f"{self.base_url}{possible_href}"

                if not next_url or not page_codes:
                    break

                current_url = next_url
                page_num += 1
                time.sleep(delay)

        except Exception as e:
            if callback:
                callback(f"❌ 页面提取异常: {e}")
        finally:
            if driver:
                try:
                    driver.quit()
                except Exception:
                    pass

        # Deduplicate
        seen = set()
        unique = []
        for c in video_codes:
            if c not in seen:
                seen.add(c)
                unique.append(c)
        return unique

    def get_video_magnets_with_driver(self, driver, video_code, prefer_sub=False, callback=None):
        url = f"{self.base_url}/{video_code}"
        max_retries = 3

        for attempt in range(max_retries):
            try:
                driver.get(url)
                self._pass_age_verification(driver)

                page_source = driver.page_source
                soup = BeautifulSoup(page_source, 'html.parser')
                page_title = driver.title

                # Detect Cloudflare Access Denied Page -> Backoff 3.5s & Auto Retry
                if "Access denied" in page_title or "Cloudflare" in page_title or "403 Forbidden" in page_title:
                    if attempt < max_retries - 1:
                        if callback:
                            callback(f"  ⚠️ [{video_code}] 触发 Cloudflare 频率限制，退避休眠 3.5 秒后自动重试 ({attempt + 1}/{max_retries})...")
                        time.sleep(3.5 + random.uniform(0.5, 1.2))
                        continue

                # Smart wait for AJAX magnet table rows
                try:
                    WebDriverWait(driver, 4).until(
                        lambda d: len(d.find_elements(By.CSS_SELECTOR, '#magnet-table tr a[href*="magnet"]')) > 0
                    )
                except TimeoutException:
                    time.sleep(0.8)

                page_source = driver.page_source
                soup = BeautifulSoup(page_source, 'html.parser')

                # Extract Cover Image URL (<a class="bigImage" href="/pics/cover/...">)
                cover_url = ""
                big_img_el = soup.select_one('a.bigImage') or soup.select_one('a.bigImage img') or soup.select_one('.screencap img')
                if big_img_el:
                    src = big_img_el.get('href') or big_img_el.get('src') or ""
                    if src:
                        if src.startswith('http'):
                            cover_url = src
                        else:
                            cover_url = f"{self.base_url}{src}"

                title = ""
                title_el = soup.select_one('h2.entry-title') or soup.select_one('h3')
                if title_el:
                    title = title_el.get_text(strip=True)
                else:
                    title_el = soup.select_one('title')
                    if title_el:
                        title = title_el.get_text(strip=True).replace(' - JavBus', '')

                magnets = []
                magnet_table = soup.select_one('#magnet-table')
                if magnet_table:
                    for tr in magnet_table.select('tr'):
                        tds = tr.select('td')
                        if len(tds) >= 1:
                            link = tds[0].select_one('a[href*="magnet"]')
                            if link:
                                magnet_href = link.get('href', '')
                                if magnet_href.startswith('magnet:'):
                                    name_text = link.get_text(strip=True)
                                    size = tds[1].get_text(strip=True) if len(tds) > 1 else ''
                                    date = tds[2].get_text(strip=True) if len(tds) > 2 else ''
                                    has_sub = any('字幕' in a.get_text() for a in tds[0].select('a')) or '字幕' in tr.get_text()
                                    magnets.append({
                                        'magnet': magnet_href,
                                        'name': name_text,
                                        'size': size,
                                        'date': date,
                                        'has_sub': has_sub,
                                    })

                if not magnets:
                    return video_code, title, None, None, cover_url

                if prefer_sub:
                    sub_magnets = [m for m in magnets if m['has_sub']]
                    if sub_magnets:
                        best = sub_magnets[0]
                        return video_code, title, best['magnet'], f"[字幕] {best['name']} | {best['size']}", cover_url

                best = magnets[0]
                sub_tag = "[字幕] " if best['has_sub'] else ""
                return video_code, title, best['magnet'], f"{sub_tag}{best['name']} | {best['size']}", cover_url

            except Exception as e:
                if attempt < max_retries - 1:
                    time.sleep(2.0)
                    continue
                if callback:
                    callback(f"❌ 抓取 {video_code} 失败: {e}")
                return video_code, "", None, None, ""

        return video_code, "", None, None, ""


class ModernCrawlerApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("⚡ JavBus 磁力链接极速抓取器 v2.6 (静默无弹窗复制)")
        self.geometry("1280x850")
        self.minsize(1040, 700)

        self.crawler = JavbusSeleniumCrawler()
        self.crawling = False
        self.image_cache = {}
        self._run_id = 0

        self._create_layout()

        self.bind_all("<MouseWheel>", self._card_global_wheel)

    def _create_layout(self):
        # Grid layout (1 row x 2 cols)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # ------------------ LEFT SIDEBAR ------------------
        self.sidebar = ctk.CTkFrame(self, width=280, corner_radius=0)
        self.sidebar.grid(row=0, column=0, sticky="nsew", padx=0, pady=0)
        self.sidebar.grid_rowconfigure(12, weight=1)

        # Logo & Title
        self.logo_label = ctk.CTkLabel(
            self.sidebar, 
            text="⚡ Magnet Downer", 
            font=ctk.CTkFont(size=20, weight="bold")
        )
        self.logo_label.grid(row=0, column=0, padx=20, pady=(20, 5), sticky="w")
        
        self.sub_logo = ctk.CTkLabel(
            self.sidebar, 
            text="大图封面 + 静默右键复制", 
            font=ctk.CTkFont(size=12),
            text_color="gray"
        )
        self.sub_logo.grid(row=1, column=0, padx=20, pady=(0, 15), sticky="w")

        # Input Form
        self.lbl_url = ctk.CTkLabel(self.sidebar, text="演员主页 / 番号 URL:", font=ctk.CTkFont(size=13, weight="bold"))
        self.lbl_url.grid(row=2, column=0, padx=20, pady=(5, 2), sticky="w")
        
        self.entry_url = ctk.CTkEntry(self.sidebar, placeholder_text="https://www.javbus.com/star/zi1")
        self.entry_url.insert(0, "https://www.javbus.com/star/zi1")
        self.entry_url.grid(row=3, column=0, padx=20, pady=(0, 10), sticky="ew")

        # Options Card
        self.opt_frame = ctk.CTkFrame(self.sidebar, corner_radius=8)
        self.opt_frame.grid(row=4, column=0, padx=15, pady=5, sticky="ew")

        # Proxy Setting Input
        self.lbl_proxy = ctk.CTkLabel(self.opt_frame, text="🌐 网络代理地址 (Proxy):", font=ctk.CTkFont(size=12, weight="bold"))
        self.lbl_proxy.grid(row=0, column=0, padx=10, pady=(8, 2), sticky="w")
        self.entry_proxy = ctk.CTkEntry(self.opt_frame, placeholder_text="http://127.0.0.1:10808")
        self.entry_proxy.insert(0, "http://127.0.0.1:10808")
        self.entry_proxy.grid(row=1, column=0, padx=10, pady=(0, 8), sticky="ew")

        self.chk_use_proxy = ctk.CTkCheckBox(self.opt_frame, text="启用网络代理")
        self.chk_use_proxy.select()
        self.chk_use_proxy.grid(row=2, column=0, padx=10, pady=(0, 8), sticky="w")

        self.lbl_max = ctk.CTkLabel(self.opt_frame, text="最大爬取数量 (0=全部):")
        self.lbl_max.grid(row=3, column=0, padx=10, pady=(4, 2), sticky="w")
        self.entry_max = ctk.CTkEntry(self.opt_frame, width=100)
        self.entry_max.insert(0, "0")
        self.entry_max.grid(row=4, column=0, padx=10, pady=(0, 8), sticky="w")

        self.lbl_threads = ctk.CTkLabel(self.opt_frame, text="后台并发窗口数 (推荐1-2):")
        self.lbl_threads.grid(row=5, column=0, padx=10, pady=(4, 2), sticky="w")
        self.slider_threads = ctk.CTkSlider(self.opt_frame, from_=1, to=4, number_of_steps=3)
        self.slider_threads.set(1)
        self.slider_threads.grid(row=6, column=0, padx=10, pady=(0, 2), sticky="ew")
        self.lbl_threads_val = ctk.CTkLabel(self.opt_frame, text="1 窗口并发 (防封最稳)", text_color="#2ecc71")
        self.lbl_threads_val.grid(row=7, column=0, padx=10, pady=(0, 8), sticky="w")
        
        def _update_thread_label(val):
            v = int(val)
            t_text = f"{v} 窗口并发 (防封最稳)" if v == 1 else f"{v} 窗口并发"
            t_color = "#2ecc71" if v == 1 else "gray"
            self.lbl_threads_val.configure(text=t_text, text_color=t_color)

        self.slider_threads.configure(command=_update_thread_label)

        self.chk_prefer_sub = ctk.CTkCheckBox(self.opt_frame, text="优先选择中文字幕")
        self.chk_prefer_sub.select()
        self.chk_prefer_sub.grid(row=8, column=0, padx=10, pady=(6, 8), sticky="w")

        # Action Buttons
        self.btn_start = ctk.CTkButton(
            self.sidebar, 
            text="▶ 开始极速爬取", 
            font=ctk.CTkFont(size=14, weight="bold"),
            height=40,
            command=self.start_crawl
        )
        self.btn_start.grid(row=5, column=0, padx=20, pady=(15, 8), sticky="ew")

        self.btn_stop = ctk.CTkButton(
            self.sidebar, 
            text="⏹ 停止任务", 
            fg_color="#e74c3c", 
            hover_color="#c0392b",
            font=ctk.CTkFont(size=14, weight="bold"),
            height=36,
            state="disabled",
            command=self.stop_crawl
        )
        self.btn_stop.grid(row=6, column=0, padx=20, pady=(0, 10), sticky="ew")

        # Appearance Switch
        self.lbl_theme = ctk.CTkLabel(self.sidebar, text="主题模式:", font=ctk.CTkFont(size=12))
        self.lbl_theme.grid(row=13, column=0, padx=20, pady=(10, 0), sticky="w")
        self.option_theme = ctk.CTkOptionMenu(
            self.sidebar, 
            values=["Dark", "Light", "System"],
            command=lambda mode: ctk.set_appearance_mode(mode)
        )
        self.option_theme.grid(row=14, column=0, padx=20, pady=(0, 20), sticky="ew")

        # ------------------ RIGHT MAIN CONTENT ------------------
        self.main_frame = ctk.CTkFrame(self, corner_radius=0, fg_color="transparent")
        self.main_frame.grid(row=0, column=1, sticky="nsew", padx=20, pady=20)
        self.main_frame.grid_columnconfigure(0, weight=1)
        self.main_frame.grid_rowconfigure(2, weight=1)

        # Top Control Bar
        self.top_bar = ctk.CTkFrame(self.main_frame, corner_radius=10)
        self.top_bar.grid(row=0, column=0, sticky="ew", padx=0, pady=(0, 15))

        self.lbl_status = ctk.CTkLabel(
            self.top_bar, 
            text="状态: 就绪", 
            font=ctk.CTkFont(size=14, weight="bold")
        )
        self.lbl_status.pack(side="left", padx=15, pady=12)

        self.lbl_count = ctk.CTkLabel(
            self.top_bar, 
            text="结果: 0 条", 
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color="#3498db"
        )
        self.lbl_count.pack(side="right", padx=15, pady=12)

        self.btn_export = ctk.CTkButton(
            self.top_bar, 
            text="📁 导出 CSV", 
            width=100,
            command=self.export_csv
        )
        self.btn_export.pack(side="right", padx=5, pady=12)

        self.btn_copy_all = ctk.CTkButton(
            self.top_bar, 
            text="📋 复制全部磁链", 
            width=120,
            command=self.copy_all_magnets
        )
        self.btn_copy_all.pack(side="right", padx=5, pady=12)

        # Progress Bar
        self.progress_bar = ctk.CTkProgressBar(self.main_frame)
        self.progress_bar.set(0)
        self.progress_bar.grid(row=1, column=0, sticky="ew", padx=0, pady=(0, 15))

        # Tabview for Results & Logs
        self.tabview = ctk.CTkTabview(self.main_frame)
        self.tabview.grid(row=2, column=0, sticky="nsew", padx=0, pady=0)

        self.tab_cards = self.tabview.add("🎬 封面图文视图")
        self.tab_results = self.tabview.add("📊 简洁表格视图")
        self.tab_logs = self.tabview.add("📝 运行日志")

        # Set default active tab
        self.tabview.set("🎬 封面图文视图")

        # ---------------- TAB 1: CARD VIEW ----------------
        self.tab_cards.grid_columnconfigure(0, weight=1)
        self.tab_cards.grid_rowconfigure(0, weight=1)

        self.card_scroll_frame = ctk.CTkScrollableFrame(self.tab_cards, corner_radius=6)
        self.card_scroll_frame.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)
        self.card_scroll_frame.grid_columnconfigure(0, weight=1)

        # ---------------- TAB 2: TREEVIEW TABLE ----------------
        self.tab_results.grid_columnconfigure(0, weight=1)
        self.tab_results.grid_rowconfigure(0, weight=1)

        self.tree_frame = ctk.CTkFrame(self.tab_results, fg_color="transparent")
        self.tree_frame.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)
        self.tree_frame.grid_columnconfigure(0, weight=1)
        self.tree_frame.grid_rowconfigure(0, weight=1)

        columns = ("code", "title", "info", "magnet")
        self.tree = ttk.Treeview(self.tree_frame, columns=columns, show="headings", selectmode="extended")
        self.tree.heading("code", text="番号")
        self.tree.heading("title", text="标题")
        self.tree.heading("info", text="资源信息")
        self.tree.heading("magnet", text="磁力链接")

        self.tree.column("code", width=120, minwidth=80, anchor="center")
        self.tree.column("title", width=250, minwidth=150)
        self.tree.column("info", width=220, minwidth=150)
        self.tree.column("magnet", width=300, minwidth=150)

        vsb = ttk.Scrollbar(self.tree_frame, orient="vertical", command=self.tree.yview)
        hsb = ttk.Scrollbar(self.tree_frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")

        self._create_tree_context_menu()

        # ---------------- TAB 3: LOGS ----------------
        self.tab_logs.grid_columnconfigure(0, weight=1)
        self.tab_logs.grid_rowconfigure(0, weight=1)

        self.txt_logs = ctk.CTkTextbox(
            self.tab_logs, 
            font=ctk.CTkFont(family="Consolas", size=12),
            activate_scrollbars=True
        )
        self.txt_logs.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)

    def _create_tree_context_menu(self):
        self.tree_menu = tk.Menu(self.tree, tearoff=0)
        self.tree_menu.add_command(label="复制", command=self._copy_selected_magnet)
        self.tree_menu.add_command(label="复制全行", command=self._copy_selected_row)
        self.tree_menu.add_separator()
        self.tree_menu.add_command(label="清空所有", command=self._clear_tree)

        def show_menu(event):
            item = self.tree.identify_row(event.y)
            if item:
                if item not in self.tree.selection():
                    self.tree.selection_set(item)
                self.tree_menu.tk_popup(event.x_root, event.y_root)

        self.tree.bind("<Button-3>", show_menu)

    def _copy_selected_magnet(self):
        selected = self.tree.selection()
        if not selected:
            return
        magnets = []
        for item in selected:
            val = self.tree.item(item, "values")
            if len(val) >= 4 and val[3]:
                magnets.append(val[3])
        if magnets:
            self.clipboard_clear()
            self.clipboard_append("\n".join(magnets))

    def _copy_selected_row(self):
        selected = self.tree.selection()
        if not selected:
            return
        lines = []
        for item in selected:
            val = self.tree.item(item, "values")
            lines.append(" | ".join(val))
        if lines:
            self.clipboard_clear()
            self.clipboard_append("\n".join(lines))

    def _clear_tree(self):
        for item in self.tree.get_children():
            self.tree.delete(item)
        for widget in self.card_scroll_frame.winfo_children():
            widget.destroy()
        self.crawler.results.clear()
        self.image_cache.clear()
        self.lbl_count.configure(text="结果: 0 条")

    def log(self, msg):
        self.after(0, self._log_now, msg)

    def _log_now(self, msg):
        timestamp = time.strftime("[%H:%M:%S] ")
        self.txt_logs.insert("end", f"{timestamp}{msg}\n")
        self.txt_logs.see("end")

    def update_status(self, text):
        self.after(0, lambda: self.lbl_status.configure(text=f"状态: {text}"))

    def update_progress(self, current, total):
        def _do():
            if total > 0:
                self.progress_bar.set(current / total)
        self.after(0, _do)

    def _bind_selectable_text_menu(self, textbox_widget, fallback_full_text=""):
        menu = tk.Menu(textbox_widget, tearoff=0)

        def do_copy():
            # Check if there is mouse-highlighted selected text
            try:
                sel_text = textbox_widget.get("sel.first", "sel.last").strip()
                if sel_text:
                    self.clipboard_clear()
                    self.clipboard_append(sel_text)
                    return
            except Exception:
                pass

            # Fallback to full text if nothing highlighted (silently copy to clipboard)
            text_val = fallback_full_text or textbox_widget.get("1.0", "end-1c").strip()
            if text_val:
                self.clipboard_clear()
                self.clipboard_append(text_val)

        menu.add_command(label="复制", command=do_copy)

        def show_menu(event):
            try:
                menu.tk_popup(event.x_root, event.y_root)
            finally:
                menu.grab_release()

        textbox_widget.bind("<Button-3>", show_menu)

    def _card_global_wheel(self, event):
        try:
            canvas = self.card_scroll_frame._parent_canvas
        except AttributeError:
            return None

        widget = event.widget
        in_card_area = False
        while widget is not None:
            if widget is self.card_scroll_frame or widget is canvas or widget is canvas.master:
                in_card_area = True
                break
            widget = getattr(widget, "master", None)

        if not in_card_area:
            return None

        if event.num == 4:
            canvas.yview_scroll(-3, "units")
        elif event.num == 5:
            canvas.yview_scroll(3, "units")
        else:
            canvas.yview_scroll(int(-event.delta / 2), "units")
        return "break"

    def add_result(self, code, title, magnet, info, cover_url, proxy=None):
        def _do():
            # Add to treeview table
            self.tree.insert("", "end", values=(code, title, info or "无磁链", magnet or ""))
            count = len(self.tree.get_children())
            self.lbl_count.configure(text=f"结果: {count} 条")

            # Create Modern Cover Card
            card = ctk.CTkFrame(self.card_scroll_frame, corner_radius=10)
            card.pack(fill="x", expand=True, padx=5, pady=8)
            card.grid_columnconfigure(1, weight=1)

            # Cover Image Placeholder (170x115)
            img_label = ctk.CTkLabel(
                card, 
                text="🖼️ 加载封面中...", 
                width=170, 
                height=115, 
                fg_color=("#e0e0e0", "#2b2b2b"),
                corner_radius=6
            )
            img_label.grid(row=0, column=0, rowspan=4, padx=12, pady=12, sticky="nw")

            # Async fetch cover image
            if cover_url:
                threading.Thread(
                    target=self._fetch_and_render_cover, 
                    args=(cover_url, img_label, proxy), 
                    daemon=True
                ).start()

            # Right Details (Selectable Text Box for Title)
            title_text = f"【{code}】{title}" if title else code
            txt_title = ctk.CTkTextbox(
                card, 
                height=50, 
                font=ctk.CTkFont(size=14, weight="bold"),
                fg_color="transparent",
                activate_scrollbars=False,
                wrap="word",
                border_width=0
            )
            txt_title.insert("1.0", title_text)
            txt_title.grid(row=0, column=1, padx=(0, 12), pady=(10, 2), sticky="ew")
            self._bind_selectable_text_menu(txt_title, fallback_full_text=title_text)

            # Info Badge (Selectable Text Box for Info)
            info_str = info if info else "暂无可用磁力链接 (或合集碟)"
            txt_info = ctk.CTkTextbox(
                card, 
                height=30, 
                font=ctk.CTkFont(size=12),
                text_color="#2ecc71" if magnet else "#e74c3c",
                fg_color="transparent",
                activate_scrollbars=False,
                wrap="word",
                border_width=0
            )
            txt_info.insert("1.0", info_str)
            txt_info.grid(row=1, column=1, padx=(0, 12), pady=(0, 4), sticky="ew")
            self._bind_selectable_text_menu(txt_info, fallback_full_text=info_str)

            # Buttons row
            btn_frame = ctk.CTkFrame(card, fg_color="transparent")
            btn_frame.grid(row=2, column=1, padx=(0, 12), pady=(0, 12), sticky="w")

            if magnet:
                btn_copy = ctk.CTkButton(
                    btn_frame, 
                    text="📋 复制磁链", 
                    width=100, 
                    height=28,
                    font=ctk.CTkFont(size=12),
                    command=lambda m=magnet: self._copy_single_magnet(m)
                )
                btn_copy.pack(side="left", padx=(0, 8))

            video_url = f"{self.crawler.base_url}/{code}"
            btn_open = ctk.CTkButton(
                btn_frame, 
                text="🌐 网页查看", 
                width=90, 
                height=28,
                fg_color="gray",
                hover_color="#555555",
                font=ctk.CTkFont(size=12),
                command=lambda u=video_url: webbrowser.open(u)
            )
            btn_open.pack(side="left")

        self.after(0, _do)

    def _fetch_and_render_cover(self, cover_url, img_label, proxy=None):
        try:
            formatted_proxy = None
            if proxy and proxy.strip():
                p = proxy.strip()
                if not p.startswith(('http://', 'https://', 'socks5://')):
                    p = f"http://{p}"
                formatted_proxy = p

            headers = {
                "User-Agent": random.choice(USER_AGENTS),
                "Referer": "https://www.javbus.com/",
                "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8"
            }

            kwargs = {
                "headers": headers,
                "timeout": 12.0,
                "follow_redirects": True
            }
            if formatted_proxy:
                kwargs["proxy"] = formatted_proxy

            with httpx.Client(**kwargs) as client:
                resp = client.get(cover_url)
                if resp.status_code == 200:
                    img_data = resp.content
                    pil_img = Image.open(io.BytesIO(img_data))
                    
                    # Resize to 1.2x enlarged thumbnail size (170x115)
                    pil_img = pil_img.resize((170, 115), Image.Resampling.LANCZOS)
                    ctk_img = ctk.CTkImage(light_image=pil_img, dark_image=pil_img, size=(170, 115))
                    
                    # Update label on UI thread
                    self.after(0, lambda: img_label.configure(image=ctk_img, text=""))
                    self.image_cache[cover_url] = ctk_img
                else:
                    self.after(0, lambda: img_label.configure(text="🖼️ 无封面"))
        except Exception:
            self.after(0, lambda: img_label.configure(text="🖼️ 无封面"))

    def _copy_single_magnet(self, magnet_str):
        self.clipboard_clear()
        self.clipboard_append(magnet_str)
        # Silent copy to clipboard without popups!

    def start_crawl(self):
        if self.crawling:
            return

        url = self.entry_url.get().strip()
        if not url:
            messagebox.showwarning("提示", "请输入演员主页 URL 或番号地址")
            return

        proxy = None
        if self.chk_use_proxy.get():
            proxy = self.entry_proxy.get().strip()

        self.crawling = True
        self.crawler._stop = False
        self._run_id += 1
        my_run_id = self._run_id
        self.crawler.results.clear()
        self._clear_tree()

        self.btn_start.configure(state="disabled")
        self.btn_stop.configure(state="normal")
        self.progress_bar.set(0)

        threading.Thread(target=self._run_crawl_thread, args=(url, proxy, my_run_id), daemon=True).start()

    def stop_crawl(self):
        self.crawling = False
        self.crawler.stop()
        self.btn_start.configure(state="normal")
        self.btn_stop.configure(state="disabled")
        self.update_status("正在停止...")
        self.log("⏹ 用户手动停止任务")

    def _run_crawl_thread(self, url, proxy, run_id):
        try:
            self.log(f"🚀 开始任务: {url}")
            if proxy:
                self.log(f"🌐 启用网络代理服务器: {proxy}")
            else:
                self.log("🌐 直连模式 (未启用代理)")

            # Check direct video code
            code_match = re.match(r'^[A-Za-z]{2,6}-\d{3,5}$', url)
            if code_match:
                videos = [url.upper()]
            else:
                self.update_status("正在启动 Selenium 极速提取番号列表...")
                videos = self.crawler.get_star_page_videos(
                    url, 
                    proxy=proxy,
                    callback=self.log
                )

            if not videos:
                self.log("⚠️ 未能提取到任何有效的视频番号！")
                self.update_status("无可用番号")
                return

            max_num = self.entry_max.get().strip()
            if max_num.isdigit() and int(max_num) > 0:
                videos = videos[:int(max_num)]

            total = len(videos)
            self.log(f"📊 共确定 {total} 个目标番号，启动 Selenium 窗口线程解析磁链与封面...")
            self.update_status(f"开始爬取 (共 {total} 个)")

            num_threads = int(self.slider_threads.get())
            prefer_sub = self.chk_prefer_sub.get()

            completed = 0
            success_count = 0
            stats_lock = threading.Lock()

            # Worker task (reuses driver for entire chunk with human-like pacing delay)
            def worker_task(code_chunk):
                nonlocal completed, success_count
                driver = None
                try:
                    driver = self.crawler.create_driver(proxy=proxy)
                    for code in code_chunk:
                        if not self.crawling or run_id != self._run_id:
                            break

                        self.log(f"🔍 正在解析番号: {code}")
                        vcode, title, magnet, info, cover_url = self.crawler.get_video_magnets_with_driver(
                            driver, code, prefer_sub=prefer_sub, callback=self.log
                        )

                        with stats_lock:
                            completed += 1
                            if magnet:
                                success_count += 1
                            self.crawler.results.append({
                                'code': vcode,
                                'title': title,
                                'magnet': magnet or '',
                                'info': info or '',
                                'cover_url': cover_url or ''
                            })

                        self.update_progress(completed, total)
                        self.update_status(f"进度: {completed}/{total} [{vcode}]")

                        self.add_result(vcode, title, magnet, info, cover_url, proxy=proxy)

                        if magnet:
                            self.log(f"  ✓ [{vcode}] 抓取成功: {info}")
                        else:
                            self.log(f"  ✗ [{vcode}] 无可用磁链 (无资源或合集碟)")

                        # Human-like pacing delay (1.2s ~ 2.2s) to prevent Cloudflare rate limiting
                        time.sleep(random.uniform(1.2, 2.2))

                except Exception as exc:
                    self.log(f"❌ 浏览器线程异常: {exc}")
                finally:
                    if driver:
                        try:
                            driver.quit()
                        except Exception:
                            pass

            # Divide video list into chunks
            chunk_size = (total + num_threads - 1) // num_threads
            chunks = [videos[i:i + chunk_size] for i in range(0, total, chunk_size)]

            threads = []
            for chunk in chunks:
                if chunk:
                    t = threading.Thread(target=worker_task, args=(chunk,), daemon=True)
                    t.start()
                    threads.append(t)

            for t in threads:
                t.join()

            self.log(f"🎉 任务完成！共成功抓取 {success_count}/{total} 条磁力链接！")
            self.update_status(f"抓取完成 ({success_count}/{total})")

        except Exception as e:
            self.log(f"❌ 发生致命错误: {e}")
            self.update_status("运行异常")
        finally:
            self.after(0, self._reset_ui_state)

    def _reset_ui_state(self):
        self.crawling = False
        self.btn_start.configure(state="normal")
        self.btn_stop.configure(state="disabled")

    def export_csv(self):
        if not self.crawler.results and not self.tree.get_children():
            messagebox.showinfo("提示", "暂无可导出的数据结果！")
            return

        path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV 文件", "*.csv"), ("所有文件", "*.*")],
            initialfile=f"JavBus磁链结果_{time.strftime('%Y%m%d_%H%M%S')}.csv"
        )
        if not path:
            return

        try:
            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f)
                writer.writerow(["番号", "标题", "资源信息", "磁力链接", "封面图片URL"])
                for r in self.crawler.results:
                    writer.writerow([r['code'], r['title'], r['info'], r['magnet'], r.get('cover_url', '')])
            messagebox.showinfo("成功", f"导出成功！已保存至:\n{path}")
        except Exception as e:
            messagebox.showerror("错误", f"导出失败: {e}")

    def copy_all_magnets(self):
        magnets = [r['magnet'] for r in self.crawler.results if r.get('magnet')]
        if not magnets:
            messagebox.showinfo("提示", "当前列表中无可用的磁力链接！")
            return

        self.clipboard_clear()
        self.clipboard_append("\n".join(magnets))
        # Silent copy to clipboard without popups!


if __name__ == "__main__":
    app = ModernCrawlerApp()
    app.mainloop()

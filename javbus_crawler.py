import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox, filedialog
import threading
import csv
import re
import time
from bs4 import BeautifulSoup

# Try to import selenium
try:
    from selenium import webdriver
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.common.exceptions import TimeoutException, NoSuchElementException
    SELENIUM_AVAILABLE = True
except ImportError:
    SELENIUM_AVAILABLE = False

VIDEO_CODE_RE = re.compile(r'[A-Z]{2,6}-\d{3,5}')
STAR_URL_RE = re.compile(r'/star/([^/?#]+)')
INVALID_CODES = {'HTTP', 'HTML', 'HTTPS'}


class JavbusCrawler:
    BASE_URL = "https://www.javbus.com"

    def __init__(self):
        self.driver = None
        self.results = []
        self._stop = False

    def _get_driver(self):
        if not SELENIUM_AVAILABLE:
            raise RuntimeError("Selenium not installed. Run: pip install selenium")
        if self.driver:
            return self.driver

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

        for BrowserClass, OptionsClass in browsers:
            try:
                opts = OptionsClass()
                opts.add_argument('--headless')
                opts.add_argument('--no-sandbox')
                opts.add_argument('--disable-gpu')
                opts.add_argument('--disable-extensions')
                opts.add_argument('--log-level=3')
                opts.add_argument('--window-size=1920,1080')
                opts.add_argument('--lang=zh-CN')
                opts.add_experimental_option('excludeSwitches', ['enable-logging'])
                self.driver = BrowserClass(options=opts)
                self.driver.set_page_load_timeout(30)
                return self.driver
            except Exception:
                self.driver = None
                continue

        raise RuntimeError("Cannot start browser. Install Chrome or Edge.")

    def _pass_age_verification(self):
        try:
            try:
                WebDriverWait(self.driver, 10).until(
                    EC.presence_of_element_located(
                        (By.CSS_SELECTOR, "input[type='checkbox'], input[type='radio']")
                    )
                )
            except TimeoutException:
                return False

            try:
                checkbox = self.driver.find_element(By.CSS_SELECTOR, "#form1 input[type='checkbox']")
                checkbox.click()
                submit = self.driver.find_element(By.ID, "submit")
                submit.click()
                WebDriverWait(self.driver, 10).until(
                    lambda d: d.title != "Age Verification"
                )
                return True
            except Exception:
                pass

            try:
                radios = self.driver.find_elements(By.CSS_SELECTOR, "input[type='radio']")
                if radios:
                    for radio in radios[:5]:
                        try:
                            radio.click()
                        except Exception:
                            pass
                    submit = self.driver.find_element(By.ID, "submit")
                    submit.click()
                    WebDriverWait(self.driver, 10).until(
                        lambda d: d.title != "Age Verification"
                    )
                    return True
            except Exception:
                pass

            return False
        except Exception as e:
            print(f"Verification error: {e}")
            return False

    def _get_star_page_videos(self, star_url, callback=None):
        driver = self.driver
        if not driver:
            return []
        video_codes = []

        try:
            driver.get(star_url)
            self._pass_age_verification()

            WebDriverWait(driver, 15).until(
                lambda d: len(VIDEO_CODE_RE.findall(d.page_source)) > 0
            )

            star_name = ''
            m = STAR_URL_RE.search(star_url)
            if m:
                star_name = m.group(1)

            page_num = 1
            while not self._stop:
                content = driver.page_source
                page_codes = []

                for match in VIDEO_CODE_RE.finditer(content):
                    code = match.group(1)
                    if code not in INVALID_CODES and len(code) > 4:
                        page_codes.append(code)

                page_codes = list(dict.fromkeys(page_codes))
                video_codes.extend(page_codes)

                if callback:
                    callback(f"第 {page_num} 页: +{len(page_codes)} (累计: {len(video_codes)})",
                           len(video_codes), len(video_codes))

                next_url = None
                if star_name:
                    escaped = re.escape(star_name)
                    next_page = page_num + 1
                    links = driver.find_elements(By.TAG_NAME, "a")
                    for link in links:
                        href = link.get_attribute("href") or ""
                        text = link.text.strip()

                        if f'/star/{star_name}/' in href:
                            pm = re.search(rf'/star/{escaped}/(\d+)', href)
                            if pm and int(pm.group(1)) == next_page:
                                next_url = href
                                break

                        if f'star/{star_name}-{next_page}' in href:
                            next_url = href
                            break

                        if text in ('\u00bb', '>', '下一页', 'Next', '＞'):
                            if f'star/{star_name}' in href:
                                next_url = href
                                break

                if not next_url:
                    break

                driver.get(next_url)
                WebDriverWait(driver, 15).until(
                    lambda d: len(VIDEO_CODE_RE.findall(d.page_source)) > 0
                )
                time.sleep(2)
                page_num += 1

        except Exception as e:
            if callback:
                callback(f"错误: {str(e)[:50]}")

        seen = set()
        unique = []
        for c in video_codes:
            if c not in seen:
                seen.add(c)
                unique.append(c)
        return unique

    def get_video_magnets(self, video_code, prefer_sub=False, callback=None):
        if not self.driver:
            return video_code, '', None, None

        url = f"{self.BASE_URL}/{video_code}"

        try:
            self.driver.get(url)
            WebDriverWait(self.driver, 15).until(
                EC.presence_of_element_located(
                    (By.CSS_SELECTOR, 'h2.entry-title, #magnet-table, .container')
                )
            )
            time.sleep(3)

            content = self.driver.page_source
            soup = BeautifulSoup(content, 'html.parser')

            title = ''
            title_el = soup.select_one('h2.entry-title')
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
                                has_sub = any('\u5b57\u5e55' in a.get_text() for a in tds[0].select('a'))
                                magnets.append({
                                    'magnet': magnet_href,
                                    'name': name_text,
                                    'size': size,
                                    'date': date,
                                    'has_sub': has_sub,
                                })

            if not magnets:
                return video_code, title, None, None

            if prefer_sub:
                sub_magnets = [m for m in magnets if m['has_sub']]
                if sub_magnets:
                    best = sub_magnets[0]
                    return video_code, title, best['magnet'], f"[字幕] {best['name']} | {best['size']}"

            best = magnets[0]
            return video_code, title, best['magnet'], f"{best['name']} | {best['size']}"

        except Exception as e:
            if callback:
                callback(f"错误: {str(e)[:50]}")
            return video_code, '', None, None

    def stop(self):
        self._stop = True
        self.cleanup()

    def cleanup(self):
        if self.driver:
            try:
                self.driver.quit()
            except Exception:
                pass
            self.driver = None


class CrawlerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("磁力链接爬虫")
        self.root.geometry("1100x620")
        self.crawler = JavbusCrawler()
        self.crawling = False
        self._apply_theme()
        self._create_widgets()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _apply_theme(self):
        style = ttk.Style()
        theme = style.theme_names()
        use_clam = 'clam' in theme
        if use_clam:
            style.theme_use('clam')

        bg = '#f0f2f5'
        card = '#ffffff'
        primary = '#4a90d9'
        hover = '#357abd'
        danger = '#e74c3c'
        danger_hover = '#c0392b'
        text = '#2c3e50'
        muted = '#7f8c8d'

        self.root.configure(bg=bg)

        style.configure('Title.TLabel', font=('Microsoft YaHei', 14, 'bold'), foreground=text, background=bg)
        style.configure('Subtitle.TLabel', font=('Microsoft YaHei', 9), foreground=muted, background=bg)
        style.configure('Card.TLabelframe', background=card, borderwidth=0)
        style.configure('Card.TLabelframe.Label', font=('Microsoft YaHei', 10, 'bold'), foreground=text, background=card)
        style.configure('Header.TFrame', background=bg)
        style.configure('Input.TEntry', fieldbackground='#f8f9fa', borderwidth=1, relief='solid')
        style.map('Input.TEntry', fieldbackground=[('focus', '#ffffff')])

        if use_clam:
            style.configure('Primary.TButton', font=('Microsoft YaHei', 9, 'bold'), foreground='white', background=primary, padding=(18, 8), borderwidth=0)
            style.map('Primary.TButton', background=[('active', hover)])
            style.configure('Danger.TButton', font=('Microsoft YaHei', 9, 'bold'), foreground='white', background=danger, padding=(18, 8), borderwidth=0)
            style.map('Danger.TButton', background=[('active', danger_hover)])
            style.configure('Action.TButton', font=('Microsoft YaHei', 9), padding=(14, 8), borderwidth=0)
            style.configure('TProgressbar', background=primary, troughcolor='#e0e0e0', thickness=6)
            style.map('TProgressbar', background=[('active', hover)])
        else:
            style.configure('Primary.TButton', font=('Microsoft YaHei', 9, 'bold'), padding=(18, 8))
            style.configure('Danger.TButton', font=('Microsoft YaHei', 9, 'bold'), padding=(18, 8))
            style.configure('Action.TButton', font=('Microsoft YaHei', 9), padding=(14, 8))

        style.configure('Status.TLabel', font=('Microsoft YaHei', 9), foreground=text, background=card)
        style.configure('Count.TLabel', font=('Microsoft YaHei', 11, 'bold'), foreground=primary, background=card)

        self.colors = {'bg': bg, 'card': card, 'primary': primary, 'danger': danger, 'text': text, 'muted': muted, 'hover': hover, 'danger_hover': danger_hover}
        self.use_clam = use_clam

    def _create_rounded_frame(self, parent, text="", padding=15):
        f = ttk.LabelFrame(parent, text=text, style='Card.TLabelframe', padding=padding)
        return f

    def _create_widgets(self):
        c = self.colors

        header = ttk.Frame(self.root, style='Header.TFrame', padding=(20, 12))
        header.pack(fill="x")
        ttk.Label(header, text="🔍 JavBus 磁力链接爬虫", style='Title.TLabel').pack(side="left")
        ttk.Label(header, text="基于 Selenium 的自动化爬虫工具", style='Subtitle.TLabel').pack(side="left", padx=(12, 0))

        main = ttk.Frame(self.root, style='Header.TFrame')
        main.pack(fill="both", expand=True, padx=16, pady=8)

        card = self._create_rounded_frame(main, text="⚙️  爬取设置")
        card.pack(fill="x", pady=(0, 8))

        row0 = ttk.Frame(card)
        row0.pack(fill="x", pady=2)
        ttk.Label(row0, text="演员主页地址", font=('Microsoft YaHei', 9, 'bold'), foreground=c['text'], background=c['card'], width=12).pack(side="left")
        self.url_var = tk.StringVar(value="https://www.javbus.com/star/zi1")
        self.url_entry = ttk.Entry(row0, textvariable=self.url_var, style='Input.TEntry')
        self.url_entry.pack(side="left", fill="x", expand=True, padx=8)
        self._add_entry_context_menu(self.url_entry)

        row1 = ttk.Frame(card)
        row1.pack(fill="x", pady=2)
        ttk.Label(row1, text="最大爬取数量", font=('Microsoft YaHei', 9, 'bold'), foreground=c['text'], background=c['card'], width=12).pack(side="left")
        self.max_var = tk.StringVar(value="0")
        self.max_entry = ttk.Entry(row1, textvariable=self.max_var, style='Input.TEntry', width=8)
        self.max_entry.pack(side="left", padx=8)
        self._add_entry_context_menu(self.max_entry)
        ttk.Label(row1, text="(0 = 全部)", font=('Microsoft YaHei', 9), foreground=c['muted'], background=c['card']).pack(side="left")

        row2 = ttk.Frame(card)
        row2.pack(fill="x", pady=2)
        self.prefer_sub = tk.BooleanVar(value=True)
        ttk.Checkbutton(row2, text="优先选择带字幕资源", variable=self.prefer_sub, style='TCheckbutton').pack(side="left")

        mid = self._create_rounded_frame(main, text="📊  运行状态")
        mid.pack(fill="x", pady=(8, 8))

        btn_row = ttk.Frame(mid)
        btn_row.pack(fill="x", pady=(0, 8))
        self.start_btn = ttk.Button(btn_row, text="▶  开始爬取", command=self.start, style='Primary.TButton')
        self.start_btn.pack(side="left", padx=(0, 6))
        self.stop_btn = ttk.Button(btn_row, text="⏹  停止", command=self.stop_crawl, state="disabled", style='Danger.TButton')
        self.stop_btn.pack(side="left", padx=(0, 6))
        ttk.Button(btn_row, text="📁  导出 CSV", command=self.export, style='Action.TButton').pack(side="left", padx=(0, 6))
        ttk.Button(btn_row, text="📋  复制磁力链接", command=self.copy_magnets, style='Action.TButton').pack(side="left")

        stat_row = ttk.Frame(mid)
        stat_row.pack(fill="x")
        self.status_var = tk.StringVar(value="就绪")
        ttk.Label(stat_row, textvariable=self.status_var, style='Status.TLabel').pack(side="left")
        self.count_var = tk.StringVar(value="0 条结果")
        ttk.Label(stat_row, textvariable=self.count_var, style='Count.TLabel').pack(side="right")

        self.progress = ttk.Progressbar(mid, mode='determinate')
        self.progress.pack(fill="x", pady=(8, 0))

        paned = ttk.PanedWindow(main, orient="horizontal")
        paned.pack(fill="both", expand=True)

        log_card = self._create_rounded_frame(paned, text="📝  运行日志")
        self.log = scrolledtext.ScrolledText(log_card, wrap="word", font=('Consolas', 9), bg=c['card'], fg=c['text'], insertbackground=c['primary'], relief='flat', borderwidth=0)
        self.log.pack(fill="both", expand=True)
        self.log.bind('<Control-a>', self._select_all)
        self.log.bind('<Control-c>', self._copy_text)
        self._add_context_menu(self.log)
        paned.add(log_card, weight=1)

        res_card = self._create_rounded_frame(paned, text="🎬  爬取结果")
        self.res = scrolledtext.ScrolledText(res_card, wrap="word", font=('Microsoft YaHei', 9), bg=c['card'], fg=c['text'], insertbackground=c['primary'], relief='flat', borderwidth=0)
        self.res.pack(fill="both", expand=True)
        self.res.bind('<Control-a>', self._select_all)
        self.res.bind('<Control-c>', self._copy_text)
        self._add_context_menu(self.res)
        paned.add(res_card, weight=2)

    def _add_context_menu(self, widget):
        menu = tk.Menu(widget, tearoff=0)
        menu.add_command(label="复制", command=lambda w=widget: self._copy_widget_text(w))
        menu.add_command(label="全选", command=lambda w=widget: self._select_widget_all(w))
        menu.add_separator()
        menu.add_command(label="清空", command=lambda w=widget: self._clear_widget(w))

        def show_menu(event):
            try:
                menu.tk_popup(event.x_root, event.y_root)
            finally:
                menu.grab_release()

        widget.bind('<Button-3>', show_menu)
        widget.bind('<Button-2>', show_menu)

    def _add_entry_context_menu(self, entry):
        menu = tk.Menu(entry, tearoff=0)
        menu.add_separator()
        menu.add_command(label="剪切", command=lambda: self._entry_cut(entry))
        menu.add_command(label="复制", command=lambda: self._entry_copy(entry))
        menu.add_command(label="粘贴", command=lambda: self._entry_paste(entry))
        menu.add_separator()
        menu.add_command(label="全选", command=lambda: self._entry_select_all(entry))

        def show_menu(event):
            entry.focus_set()
            try:
                menu.tk_popup(event.x_root, event.y_root)
            finally:
                menu.grab_release()

        entry.bind('<Button-3>', show_menu)

    def _entry_cut(self, entry):
        try:
            text = entry.get(sel_first=None, sel_last=None)
            self.root.clipboard_clear()
            self.root.clipboard_append(text)
            entry.delete(sel_first=None, sel_last=None)
        except tk.TclError:
            pass

    def _entry_copy(self, entry):
        try:
            text = entry.get(sel_first=None, sel_last=None)
            self.root.clipboard_clear()
            self.root.clipboard_append(text)
        except tk.TclError:
            text = entry.get()
            self.root.clipboard_clear()
            self.root.clipboard_append(text)

    def _entry_paste(self, entry):
        try:
            text = self.root.clipboard_get()
            if entry.index('insert') != 'end':
                entry.delete('insert', 'end')
            entry.insert('insert', text)
        except tk.TclError:
            pass

    def _entry_select_all(self, entry):
        entry.selection_range(0, 'end')
        entry.focus_set()

    def _copy_widget_text(self, widget):
        try:
            text = widget.get('sel.first', 'sel.last')
            self.root.clipboard_clear()
            self.root.clipboard_append(text)
        except tk.TclError:
            pass

    def _select_widget_all(self, widget):
        widget.tag_add('sel', '1.0', 'end')
        widget.mark_set('insert', '1.0')

    def _clear_widget(self, widget):
        widget.delete('1.0', 'end')

    def _select_all(self, event):
        widget = event.widget
        widget.tag_add('sel', '1.0', 'end')
        return 'break'

    def _copy_text(self, event):
        widget = event.widget
        try:
            text = widget.get('sel.first', 'sel.last')
            self.root.clipboard_clear()
            self.root.clipboard_append(text)
        except tk.TclError:
            pass
        return 'break'

    def log_msg(self, msg):
        self.root.after(0, self._log_msg_now, msg)

    def _log_msg_now(self, msg):
        self.log.insert("end", f"{msg}\n")
        self.log.see("end")

    def _update_status(self, msg):
        self.root.after(0, self.status_var.set, msg)

    def _update_progress(self, value, maximum=None):
        def _do():
            self.progress['value'] = value
            if maximum is not None:
                self.progress['maximum'] = maximum
        self.root.after(0, _do)

    def _update_count(self, msg):
        self.root.after(0, self.count_var.set, msg)

    def _update_results(self, text):
        self.root.after(0, self._update_results_now, text)

    def _update_results_now(self, text):
        self.res.insert("end", text)
        self.res.see("end")

    def _set_final_state(self):
        def _do():
            self.crawling = False
            self.start_btn.config(state="normal")
            self.stop_btn.config(state="disabled")
        self.root.after(0, _do)

    def _on_close(self):
        self.crawling = False
        self.crawler.stop()
        self.root.destroy()

    def start(self):
        if self.crawling:
            return
        url = self.url_var.get().strip()
        if not url:
            messagebox.showerror("错误", "请输入演员主页地址")
            return

        self.crawling = True
        self.crawler._stop = False
        self.crawler.results = []
        self.start_btn.config(state="disabled")
        self.stop_btn.config(state="normal")
        self.res.delete("1.0", "end")
        self.log.delete("1.0", "end")

        threading.Thread(target=self._run, args=(url,), daemon=True).start()

    def stop_crawl(self):
        self.crawling = False
        self.crawler.stop()
        self.start_btn.config(state="normal")
        self.stop_btn.config(state="disabled")
        self.log_msg("已停止")

    def _run(self, url):
        try:
            self.log_msg(f"正在请求: {url}")
            self._update_status("正在启动浏览器...")

            if not SELENIUM_AVAILABLE:
                self.log_msg("未安装 Selenium！")
                self._set_final_state()
                return

            self.crawler._get_driver()

            self._update_status("正在获取视频列表...")
            videos = self.crawler._get_star_page_videos(url,
                callback=lambda msg, cur=0, tot=0: (self.log_msg(msg), self._update_status(msg)))

            if not videos:
                self.log_msg("未找到任何视频！")
                self._set_final_state()
                return

            mx = self.max_var.get()
            if mx.isdigit() and int(mx) > 0:
                videos = videos[:int(mx)]

            total = len(videos)
            self.log_msg(f"共找到 {total} 个视频")
            self._update_progress(0, maximum=total)

            success = 0
            prefer_sub = self.prefer_sub.get()

            for i, code in enumerate(videos):
                if not self.crawling:
                    break

                self._update_status(f"[{i+1}/{total}] {code}")
                self._update_progress(i + 1)
                self._update_count(f"{i} 条结果")
                self.log_msg(f"正在爬取: {code}")

                def make_callback():
                    def cb(m):
                        self.log_msg(m)
                    return cb

                vcode, title, magnet, info = self.crawler.get_video_magnets(
                    code, prefer_sub=prefer_sub, callback=make_callback())

                self.crawler.results.append({
                    'code': vcode,
                    'title': title,
                    'magnet': magnet or '',
                    'info': info or '',
                })

                if magnet:
                    success += 1
                    self.log_msg(f"  ✓ 成功: {info}")
                    self._update_results(f"{vcode} | {title} | {info}\n{magnet}\n\n")
                else:
                    self.log_msg(f"  ✗ 未找到磁力链接")

                time.sleep(2)

            self.log_msg(f"爬取完成！共 {success}/{total} 个视频含有磁力链接")
            self._update_status(f"完成: {success}/{total}")
            self._update_count(f"{len(self.crawler.results)} 条结果")

        except Exception as e:
            self.log_msg(f"发生错误: {e}")
            import traceback
            self.log_msg(traceback.format_exc())
        finally:
            self.crawler.cleanup()
            self._set_final_state()

    def export(self):
        if not self.crawler.results:
            messagebox.showinfo("提示", "暂无可导出的结果")
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV 文件", "*.csv"), ("所有文件", "*.*")],
            initialfile="爬取结果.csv")
        if not path:
            return
        with open(path, 'w', newline='', encoding='utf-8-sig') as f:
            w = csv.writer(f)
            w.writerow(["编号", "标题", "信息", "磁力链接"])
            for r in self.crawler.results:
                w.writerow([r['code'], r['title'], r['info'], r['magnet']])
        messagebox.showinfo("成功", f"已导出至: {path}")

    def copy_magnets(self):
        magnets = [r['magnet'] for r in self.crawler.results if r['magnet']]
        if not magnets:
            messagebox.showinfo("提示", "暂无可复制的磁力链接")
            return
        self.root.clipboard_clear()
        self.root.clipboard_append('\n'.join(magnets))
        self.root.update()
        messagebox.showinfo("已复制", f"已复制 {len(magnets)} 条磁力链接")


if __name__ == "__main__":
    root = tk.Tk()
    CrawlerApp(root)
    root.mainloop()

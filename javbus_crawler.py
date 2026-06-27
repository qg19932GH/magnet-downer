import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox, filedialog
import threading
import csv
import re
import time
import urllib.parse
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin

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
        
        # Try browsers
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
            except Exception as e:
                self.driver = None
                continue
        
        raise RuntimeError("Cannot start browser. Install Chrome or Edge.")

    def _pass_age_verification(self):
        """Pass age verification using Selenium"""
        try:
            # Wait for form elements to appear
            try:
                WebDriverWait(self.driver, 10).until(
                    EC.presence_of_element_located(
                        (By.CSS_SELECTOR, "input[type='checkbox'], input[type='radio']")
                    )
                )
            except TimeoutException:
                return False

            # Try to find and click checkbox
            try:
                checkbox = self.driver.find_element(By.CSS_SELECTOR, "#form1 input[type='checkbox']")
                checkbox.click()
                submit = self.driver.find_element(By.ID, "submit")
                submit.click()
                WebDriverWait(self.driver, 10).until(
                    lambda d: d.title != "Age Verification"
                )
                return True
            except:
                pass

            # Try quiz
            try:
                radios = self.driver.find_elements(By.CSS_SELECTOR, "input[type='radio']")
                if radios:
                    for radio in radios[:5]:
                        try:
                            radio.click()
                        except:
                            pass
                    submit = self.driver.find_element(By.ID, "submit")
                    submit.click()
                    WebDriverWait(self.driver, 10).until(
                        lambda d: d.title != "Age Verification"
                    )
                    return True
            except:
                pass

            return False
        except Exception as e:
            print(f"Verification error: {e}")
            return False

    def _get_star_page_videos(self, star_url, callback=None):
        """Get all video codes from star page using Selenium (keeps driver open)"""
        driver = self.driver
        if not driver:
            return []
        video_codes = []

        try:
            # Navigate to star page
            driver.get(star_url)

            # Pass age verification first
            self._pass_age_verification()

            # Wait for page content to load
            WebDriverWait(driver, 15).until(
                lambda d: len(re.findall(r'[A-Z]{2,6}-\d{3,5}', d.page_source)) > 0
            )
            
            # Extract star name from URL
            star_match = re.search(r'/star/([^/?#]+)', star_url)
            star_name = star_match.group(1) if star_match else ''
            
            page_num = 1
            while not self._stop:
                content = driver.page_source
                page_codes = []
                
                for match in re.finditer(r'([A-Z]{2,6}-\d{3,5})', content):
                    code = match.group(1)
                    if code not in ('HTTP', 'HTML', 'HTTPS') and len(code) > 4:
                        page_codes.append(code)
                
                page_codes = list(dict.fromkeys(page_codes))
                video_codes.extend(page_codes)
                
                if callback:
                    callback(f"Page {page_num}: +{len(page_codes)} (total: {len(video_codes)})",
                           len(video_codes), len(video_codes))
                
                # Find pagination links
                next_url = None
                links = driver.find_elements(By.TAG_NAME, "a")
                for link in links:
                    href = link.get_attribute("href") or ""
                    text = link.text.strip()
                    
                    # Pattern 1: /star/rp6/2, /star/rp6/3
                    if star_name and f'/star/{star_name}/' in href:
                        page_match = re.search(rf'/star/{re.escape(star_name)}/(\d+)', href)
                        if page_match:
                            page = int(page_match.group(1))
                            if page == page_num + 1:
                                next_url = href
                                break
                    
                    # Pattern 2: /star/rp6-2, /star/rp6-3
                    if star_name and f'{star_name}-' in href:
                        if f'star/{star_name}-{page_num + 1}' in href:
                            next_url = href
                            break
                    
                    # Pattern 3: next button
                    if text in ('»', '>', '下一页', 'Next', '＞'):
                        if f'star/{star_name}' in href:
                            next_url = href
                            break
                
                if not next_url:
                    break
                
                # Navigate to next page
                driver.get(next_url)
                WebDriverWait(driver, 15).until(
                    lambda d: len(re.findall(r'[A-Z]{2,6}-\d{3,5}', d.page_source)) > 0
                )
                page_num += 1
        
        except Exception as e:
            if callback:
                callback(f"Error: {str(e)[:50]}")
        
        # Deduplicate
        seen = set()
        unique = []
        for c in video_codes:
            if c not in seen:
                seen.add(c)
                unique.append(c)
        return unique

    def get_star_page_videos(self, star_url, callback=None):
        """Get all video codes from star page using Selenium (closes driver)"""
        driver = self._get_driver()
        try:
            return self._get_star_page_videos(star_url, callback)
        finally:
            self.driver.quit()
            self.driver = None

    def get_video_magnets(self, video_code, prefer_sub=False, callback=None):
        """Get magnet links using Selenium"""
        if not self.driver:
            return video_code, '', None, None
        
        url = f"{self.BASE_URL}/{video_code}"
        
        try:
            # Navigate to video page
            self.driver.get(url)
            # Wait for page content to load
            WebDriverWait(self.driver, 15).until(
                EC.presence_of_element_located(
                    (By.CSS_SELECTOR, 'h2.entry-title, #magnet-table, .container')
                )
            )

            # Get page source
            content = self.driver.page_source
            
            # Get title
            soup = BeautifulSoup(content, 'html.parser')
            title = ''
            title_el = soup.select_one('h2.entry-title')
            if title_el:
                title = title_el.get_text(strip=True)
            else:
                title_el = soup.select_one('title')
                if title_el:
                    title = title_el.get_text(strip=True).replace(' - JavBus', '')
            
            # Extract magnet links
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
                                # Check for subtitle button within the same <td>
                                has_sub = any('字幕' in a.get_text() for a in tds[0].select('a'))
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
                callback(f"Error: {str(e)[:50]}")
            return video_code, '', None, None

    def stop(self):
        self._stop = True
        if self.driver:
            try:
                self.driver.quit()
            except:
                pass
            self.driver = None

    def cleanup(self):
        if self.driver:
            try:
                self.driver.quit()
            except:
                pass
            self.driver = None


class CrawlerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("JavBus Magnet Crawler")
        self.root.geometry("1200x650")
        self.crawler = JavbusCrawler()
        self.crawling = False
        self._create_widgets()

    def _create_widgets(self):
        # Settings
        f = ttk.LabelFrame(self.root, text="Settings", padding=10)
        f.pack(fill="x", padx=10, pady=5)

        ttk.Label(f, text="Actor URL:").grid(row=0, column=0, sticky="w", pady=2)
        self.url_var = tk.StringVar(value="https://www.javbus.com/star/zi1")
        self.url_entry = ttk.Entry(f, textvariable=self.url_var, width=60)
        self.url_entry.grid(row=0, column=1, sticky="ew", padx=5, pady=2)
        self._add_entry_context_menu(self.url_entry)

        ttk.Label(f, text="Max videos (0=all):").grid(row=1, column=0, sticky="w", pady=2)
        self.max_var = tk.StringVar(value="0")
        self.max_entry = ttk.Entry(f, textvariable=self.max_var, width=8)
        self.max_entry.grid(row=1, column=1, sticky="w", pady=2)
        self._add_entry_context_menu(self.max_entry)

        self.prefer_sub = tk.BooleanVar(value=True)
        ttk.Checkbutton(f, text="Prefer subtitle (字幕)", variable=self.prefer_sub).grid(row=2, column=0, columnspan=2, sticky="w", pady=2)

        f.columnconfigure(1, weight=1)

        # Progress
        f = ttk.LabelFrame(self.root, text="Progress", padding=10)
        f.pack(fill="x", padx=10, pady=5)

        self.status_var = tk.StringVar(value="Ready")
        ttk.Label(f, textvariable=self.status_var).pack(anchor="w")
        self.progress = ttk.Progressbar(f, mode='determinate')
        self.progress.pack(fill="x", pady=5)

        # Buttons
        f = ttk.Frame(self.root)
        f.pack(fill="x", padx=10, pady=5)
        self.start_btn = ttk.Button(f, text="Start", command=self.start)
        self.start_btn.pack(side="left", padx=5)
        self.stop_btn = ttk.Button(f, text="Stop", command=self.stop_crawl, state="disabled")
        self.stop_btn.pack(side="left", padx=5)
        ttk.Button(f, text="Export CSV", command=self.export).pack(side="left", padx=5)
        ttk.Button(f, text="Copy Magnets", command=self.copy_magnets).pack(side="left", padx=5)

        # Log + Results side by side
        paned = ttk.PanedWindow(self.root, orient="horizontal")
        paned.pack(fill="both", expand=True, padx=10, pady=5)

        f = ttk.LabelFrame(paned, text="Log")
        self.log = scrolledtext.ScrolledText(f, wrap="word")
        self.log.pack(fill="both", expand=True, padx=5, pady=5)
        self.log.bind('<Control-a>', self._select_all)
        self.log.bind('<Control-c>', self._copy_text)
        self._add_context_menu(self.log)
        paned.add(f, weight=1)

        f = ttk.LabelFrame(paned, text="Results")
        self.res = scrolledtext.ScrolledText(f, wrap="word")
        self.res.pack(fill="both", expand=True, padx=5, pady=5)
        self.res.bind('<Control-a>', self._select_all)
        self.res.bind('<Control-c>', self._copy_text)
        self._add_context_menu(self.res)
        paned.add(f, weight=2)

    def _add_context_menu(self, widget):
        menu = tk.Menu(widget, tearoff=0)
        menu.add_command(label="Copy", command=lambda w=widget: self._copy_widget_text(w))
        menu.add_command(label="Select All", command=lambda w=widget: self._select_widget_all(w))
        menu.add_separator()
        menu.add_command(label="Clear", command=lambda w=widget: self._clear_widget(w))

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
        menu.add_command(label="Cut", command=lambda: self._entry_cut(entry))
        menu.add_command(label="Copy", command=lambda: self._entry_copy(entry))
        menu.add_command(label="Paste", command=lambda: self._entry_paste(entry))
        menu.add_separator()
        menu.add_command(label="Select All", command=lambda: self._entry_select_all(entry))

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
        self.log.insert("end", f"{msg}\n")
        self.log.see("end")
        self.root.update_idletasks()

    def start(self):
        if self.crawling:
            return
        url = self.url_var.get().strip()
        if not url:
            messagebox.showerror("Error", "Enter actor URL")
            return

        self.crawling = True
        self.crawler._stop = False
        self.crawler.results = []
        self.start_btn.config(state="disabled")
        self.stop_btn.config(state="normal")
        self.res.delete("1.0", "end")

        threading.Thread(target=self._run, args=(url,), daemon=True).start()

    def stop_crawl(self):
        self.crawling = False
        self.crawler.stop()
        self.start_btn.config(state="normal")
        self.stop_btn.config(state="disabled")
        self.log_msg("Stopped")

    def _run(self, url):
        try:
            self.log_msg(f"Fetching: {url}")
            self.status_var.set("Starting browser...")

            if not SELENIUM_AVAILABLE:
                self.log_msg("Selenium not installed!")
                return

            # Start browser
            self.crawler._get_driver()

            # Get video codes with pagination
            self.status_var.set("Fetching video list...")
            videos = self.crawler._get_star_page_videos(url,
                callback=lambda msg, cur=0, tot=0: (self.log_msg(msg), self.status_var.set(msg)))

            if not videos:
                self.log_msg("No videos found!")
                return

            mx = self.max_var.get()
            if mx.isdigit() and int(mx) > 0:
                videos = videos[:int(mx)]

            self.log_msg(f"Found {len(videos)} videos")
            self.progress['maximum'] = len(videos)

            success = 0
            prefer_sub = self.prefer_sub.get()

            for i, code in enumerate(videos):
                if not self.crawling:
                    break

                self.status_var.set(f"[{i+1}/{len(videos)}] {code}")
                self.progress['value'] = i + 1
                self.log_msg(f"Crawling: {code}")

                vcode, title, magnet, info = self.crawler.get_video_magnets(
                    code, prefer_sub=prefer_sub,
                    callback=lambda m: self.log_msg(m))
                
                self.crawler.results.append({
                    'code': vcode,
                    'title': title,
                    'magnet': magnet or '',
                    'info': info or '',
                })

                if magnet:
                    success += 1
                    self.log_msg(f"  OK: {info}")
                    self.res.insert("end", f"{vcode} | {title} | {info}\n{magnet}\n\n")
                    self.res.see("end")
                else:
                    self.log_msg(f"  No magnet found")

                time.sleep(0.2)

            self.log_msg(f"Done! {success}/{len(videos)} with magnet")
            self.status_var.set(f"Done: {success}/{len(videos)}")

        except Exception as e:
            self.log_msg(f"Error: {e}")
            import traceback
            self.log_msg(traceback.format_exc())
        finally:
            self.crawler.cleanup()
            self.crawling = False
            self.start_btn.config(state="normal")
            self.stop_btn.config(state="disabled")

    def export(self):
        if not self.crawler.results:
            messagebox.showinfo("Info", "No results")
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV", "*.csv"), ("All", "*.*")],
            initialfile="results.csv")
        if not path:
            return
        with open(path, 'w', newline='', encoding='utf-8-sig') as f:
            w = csv.writer(f)
            w.writerow(["Code", "Title", "Info", "Magnet"])
            for r in self.crawler.results:
                w.writerow([r['code'], r['title'], r['info'], r['magnet']])
        messagebox.showinfo("Success", f"Exported to {path}")

    def copy_magnets(self):
        magnets = [r['magnet'] for r in self.crawler.results if r['magnet']]
        if not magnets:
            messagebox.showinfo("Info", "No magnets to copy")
            return
        self.root.clipboard_clear()
        self.root.clipboard_append('\n'.join(magnets))
        self.root.update()
        messagebox.showinfo("Copied", f"Copied {len(magnets)} magnets")


if __name__ == "__main__":
    root = tk.Tk()
    CrawlerApp(root)
    root.mainloop()

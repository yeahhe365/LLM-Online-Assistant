import concurrent.futures
import requests
from bs4 import BeautifulSoup
import time
import os
import logging
import re
import pyperclip
from PyQt5.QtWidgets import QApplication, QWidget, QLabel, QLineEdit, QPushButton, QTextEdit, QVBoxLayout, QHBoxLayout, QMessageBox, QFileDialog, QListWidget, QComboBox
from PyQt5.QtGui import QIcon, QFont, QPalette, QColor
from PyQt5.QtCore import Qt, QThread, pyqtSignal

# 配置日志记录
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/93.0.4577.82 Safari/537.36'
}
MAX_WORKERS = 5

class ScrapingThread(QThread):
    progress_signal = pyqtSignal(str)
    finished_signal = pyqtSignal(str, int, int, int, int)

    def __init__(self, keyword, num_pages, search_engine, directory):
        super().__init__()
        self.keyword = keyword
        self.num_pages = num_pages
        self.search_engine = search_engine
        self.directory = directory
        self._stop_event = False

    def run(self):
        if self.search_engine == "Google":
            search_url = f"https://www.google.com/search?q={self.keyword}&num={self.num_pages}"
        elif self.search_engine == "Bing":
            search_url = f"https://www.bing.com/search?q={self.keyword}&count={self.num_pages}"
        elif self.search_engine == "Baidu":
            search_url = f"https://www.baidu.com/s?wd={self.keyword}&pn={self.num_pages}"
        elif self.search_engine == "Sogou":
            search_url = f"https://www.sogou.com/web?query={self.keyword}&page={self.num_pages}"
        elif self.search_engine == "DuckDuckGo":
            search_url = f"https://duckduckgo.com/?q={self.keyword}&t=h_&ia=web"
        else:
            raise ValueError(f"不支持的搜索引擎: {self.search_engine}")

        response = requests.get(search_url, headers=HEADERS)
        soup = BeautifulSoup(response.text, 'html.parser')

        search_results = soup.select('div.g') if self.search_engine == "Google" else soup.select('li.b_algo')
        results = []
        for result in search_results:
            if self._stop_event:
                break
            link = result.select_one('a')
            if link:
                url = link['href']
                title = link.text
                try:
                    date = result.select_one('span.MUxGbd.wuQ4Ob.WZ8Tjf').text if self.search_engine == "Google" else ""
                except:
                    date = "日期未找到"
                results.append((title, date, url, ""))

        with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            # 并发爬取所有网页的文字内容和链接
            page_results = list(executor.map(self.scrape_page, [url for _, _, url, _ in results]))
            text_results = [result[0] for result in page_results]
            link_results = [result[1] for result in page_results]
            button_link_results = [result[2] for result in page_results]

        # 将文字内容、链接和按钮链接添加到结果列表中
        for i, (text, links, button_links) in enumerate(zip(text_results, link_results, button_link_results)):
            results[i] = results[i][:3] + (text, links, button_links)

        file_path, words, chars_without_spaces, chars_with_spaces, non_chinese_words = self.save_results(self.keyword, results)
        with open(file_path, "r", encoding="utf-8") as file:
            content = file.read()
            pyperclip.copy(content)  # 自动复制文本内容到剪贴板
        self.finished_signal.emit(file_path, words, chars_without_spaces, chars_with_spaces, non_chinese_words)

    def scrape_page(self, url, retry_count=3):
        for attempt in range(retry_count):
            if self._stop_event:
                break
            try:
                response = requests.get(url, headers=HEADERS, timeout=30)
                response.raise_for_status()
                response.encoding = response.apparent_encoding  # 检测并转换编码
                soup = BeautifulSoup(response.text, 'html.parser')
                paragraphs = soup.find_all('p')
                text = '\n'.join([p.get_text(strip=True) for p in paragraphs])
                
                # 提取网页中的链接
                links = [link.get('href') for link in soup.find_all('a')]
                links = [link for link in links if link and (link.startswith('http') or link.startswith('www'))]
                
                # 提取网页中的按钮名称和链接
                button_links = []
                for button in soup.find_all(['button', 'input']):
                    if button.get('type') == 'submit' or button.get('type') == 'button':
                        button_name = button.get('value') or button.get_text(strip=True)
                        button_link = button.get('onclick') or button.get('formaction') or button.get('href')
                        if button_name and button_link:
                            button_links.append(f"<{button_name}>{button_link}")
                
                return text, links, button_links
            except requests.exceptions.RequestException as e:
                logging.warning(f"请求失败 (尝试 {attempt+1}/{retry_count}): {url}")
                logging.warning(f"错误信息: {e}")
                time.sleep(1)  # 等待一段时间后重试
        logging.error(f"请求失败,已达到最大重试次数: {url}")
        return "", [], []

    def save_results(self, keyword, results):
        directory = self.directory or os.path.expanduser("~/Downloads")
        file_name = f"{keyword}.txt"
        file_path = os.path.join(directory, file_name)

        with open(file_path, "w", encoding="utf-8") as file:
            file.write("你是一个知识渊博且乐于助人的人,可以回答任何问题。你的任务是回答以下由三个反引号分隔的问题。\n\n")
            file.write("问题:\n```\n{}\n```\n\n".format(keyword))
            file.write("可能这个问题,或者其中的一部分,需要从互联网上获取相关信息才能给出令人满意的答案。")
            file.write("下面由三个反引号分隔的相关搜索结果已经是从互联网上获取到的必要信息。")
            file.write("搜索结果为回答问题设定了背景,因此你无需访问互联网来回答问题。\n\n")
            file.write("尽可能以最好的方式写出对问题的全面回答。如果有必要,可以使用提供的搜索结果。\n\n")
            file.write("---\n\n")
            file.write("如果在回答中使用了任何搜索结果,请始终在相应行的末尾引用来源,类似于维基百科如何引用信息。")
            file.write("使用引用格式[[NUMBER](URL)],其中NUMBER和URL对应于以下由三个反引号分隔的提供的搜索结果。\n\n")
            file.write("以清晰的格式呈现答案。\n")
            file.write("如果有必要,使用编号列表来澄清事情\n")
            file.write("尽可能简洁地回答,最好不超过400个字。\n\n")
            file.write("---\n\n")
            file.write("如果在搜索结果中找不到足够的信息,不确定答案,尽最大努力通过使用来自搜索结果的所有信息给出有帮助的回应。记住要用简体中文回答。\n\n")
            file.write("Search results:\n")
            file.write('"""\n')
            for i, (title, date, url, text, links, button_links) in enumerate(results, start=1):
                file.write(f"NUMBER:{i}\n")
                file.write(f"URL: {url}\n")
                file.write(f"TITLE: {title}\n")
                file.write(f"CONTENT: {text}\n")
                file.write(f"LINKS: {', '.join(links)}\n")
                file.write(f"BUTTON_LINKS: {', '.join(button_links)}\n\n")
            file.write('"""\n')

        with open(file_path, "r", encoding="utf-8") as file:
            content = file.read()
            words = len(re.findall(r'[\u4e00-\u9fa5a-zA-Z]+', content))
            chars_without_spaces = len(re.findall(r'[^\s]', content))
            chars_with_spaces = len(content)
            non_chinese_words = len(re.findall(r'\b[a-zA-Z]+\b', content))

        logging.info(f"提取的文字信息已保存到: {file_path}")
        logging.info(f"字数: {words}")
        logging.info(f"字符数(不计空格): {chars_without_spaces}")
        logging.info(f"字符数(计空格): {chars_with_spaces}")
        logging.info(f"非中文单词: {non_chinese_words}")
        return file_path, words, chars_without_spaces, chars_with_spaces, non_chinese_words

    def stop(self):
        self._stop_event = True

class WebScraperGUI(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("网页爬取工具")
        self.setGeometry(100, 100, 800, 600)
        self.setWindowIcon(QIcon("icon.png"))

        layout = QHBoxLayout()
        left_layout = QVBoxLayout()
        right_layout = QVBoxLayout()

        keyword_layout = QHBoxLayout()
        keyword_label = QLabel("关键词:", self)
        self.keyword_entry = QLineEdit(self)
        self.keyword_entry.returnPressed.connect(self.start_scraping)
        keyword_layout.addWidget(keyword_label)
        keyword_layout.addWidget(self.keyword_entry)
        left_layout.addLayout(keyword_layout)

        num_pages_layout = QHBoxLayout()
        num_pages_label = QLabel("爬取页数:", self)
        self.num_pages_entry = QLineEdit(self)
        self.num_pages_entry.setPlaceholderText("默认为10")
        palette = QPalette()
        palette.setColor(QPalette.PlaceholderText, QColor(128, 128, 128))  # 设置占位符文本颜色为浅灰色
        self.num_pages_entry.setPalette(palette)
        num_pages_layout.addWidget(num_pages_label)
        num_pages_layout.addWidget(self.num_pages_entry)
        left_layout.addLayout(num_pages_layout)

        search_engine_layout = QHBoxLayout()
        search_engine_label = QLabel("搜索引擎:", self)
        self.search_engine_combo = QComboBox(self)
        self.search_engine_combo.addItems(["Google", "Bing", "Baidu", "Sogou", "DuckDuckGo"])
        search_engine_layout.addWidget(search_engine_label)
        search_engine_layout.addWidget(self.search_engine_combo)
        left_layout.addLayout(search_engine_layout)

        directory_layout = QHBoxLayout()
        directory_label = QLabel("导出目录:", self)
        self.directory_entry = QLineEdit(self)
        self.directory_entry.setPlaceholderText("默认为下载文件夹")
        directory_button = QPushButton("浏览", self)
        directory_button.clicked.connect(self.browse_directory)
        directory_layout.addWidget(directory_label)
        directory_layout.addWidget(self.directory_entry)
        directory_layout.addWidget(directory_button)
        left_layout.addLayout(directory_layout)

        buttons_layout = QHBoxLayout()
        self.start_button = QPushButton("开始爬取", self)
        self.start_button.clicked.connect(self.start_scraping)
        self.stop_button = QPushButton("停止爬取", self)
        self.stop_button.clicked.connect(self.stop_scraping)
        self.stop_button.setEnabled(False)
        buttons_layout.addWidget(self.start_button)
        buttons_layout.addWidget(self.stop_button)
        left_layout.addLayout(buttons_layout)

        self.status_label = QLabel("状态: 就绪", self)
        left_layout.addWidget(self.status_label)

        self.result_text = QTextEdit(self)
        self.result_text.setReadOnly(True)
        left_layout.addWidget(self.result_text)

        self.file_list = QListWidget(self)
        self.file_list.itemDoubleClicked.connect(self.open_file)
        right_layout.addWidget(QLabel("生成的文件列表:"))
        right_layout.addWidget(self.file_list)

        file_buttons_layout = QHBoxLayout()
        self.copy_button = QPushButton("复制", self)
        self.copy_button.clicked.connect(self.copy_file)
        self.delete_button = QPushButton("删除", self)
        self.delete_button.clicked.connect(self.delete_file)
        file_buttons_layout.addWidget(self.copy_button)
        file_buttons_layout.addWidget(self.delete_button)
        right_layout.addLayout(file_buttons_layout)

        layout.addLayout(left_layout)
        layout.addLayout(right_layout)
        self.setLayout(layout)

        self.load_file_list()

        font = QFont()
        font.setPointSize(12)
        font.setBold(True)
        self.setFont(font)

    def start_scraping(self):
        keyword = self.keyword_entry.text()
        num_pages = int(self.num_pages_entry.text() or "10")  # 默认为10
        search_engine = self.search_engine_combo.currentText()
        directory = self.directory_entry.text()

        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.keyword_entry.setEnabled(False)
        self.num_pages_entry.setEnabled(False)
        self.search_engine_combo.setEnabled(False)
        self.directory_entry.setEnabled(False)
        self.result_text.clear()
        self.status_label.setText("状态: 爬取中...")

        self.scraping_thread = ScrapingThread(keyword, num_pages, search_engine, directory)
        self.scraping_thread.progress_signal.connect(self.update_progress)
        self.scraping_thread.finished_signal.connect(self.scraping_finished)
        self.scraping_thread.start()

    def stop_scraping(self):
        self.scraping_thread.stop()
        self.scraping_thread.wait()
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.keyword_entry.setEnabled(True)
        self.num_pages_entry.setEnabled(True)
        self.search_engine_combo.setEnabled(True)
        self.directory_entry.setEnabled(True)
        self.status_label.setText("状态: 已停止")

    def update_progress(self, message):
        self.result_text.append(message)

    def scraping_finished(self, file_path, words, chars_without_spaces, chars_with_spaces, non_chinese_words):
        self.result_text.append(f"爬取完成!\n")
        self.result_text.append(f"字数: {words}\n")
        self.result_text.append(f"字符数(不计空格): {chars_without_spaces}\n")
        self.result_text.append(f"字符数(计空格): {chars_with_spaces}\n")
        self.result_text.append(f"非中文单词: {non_chinese_words}\n")
        self.result_text.append(f"文件保存位置: {file_path}\n")
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.keyword_entry.setEnabled(True)
        self.num_pages_entry.setEnabled(True)
        self.search_engine_combo.setEnabled(True)
        self.directory_entry.setEnabled(True)
        self.status_label.setText("状态: 已完成")
        QMessageBox.information(self, "爬取完成", "网页爬取已完成!")

        self.load_file_list()

    def browse_directory(self):
        directory = QFileDialog.getExistingDirectory(self, "选择导出目录")
        if directory:
            self.directory_entry.setText(directory)
            self.load_file_list()

    def load_file_list(self):
        self.file_list.clear()
        directory = self.directory_entry.text() or os.path.expanduser("~/Downloads")
        files = [f for f in os.listdir(directory) if f.endswith(".txt")]
        self.file_list.addItems(files)

    def open_file(self, item):
        directory = self.directory_entry.text() or os.path.expanduser("~/Downloads")
        file_path = os.path.join(directory, item.text())
        os.startfile(file_path)

    def copy_file(self):
        if self.file_list.currentItem():
            directory = self.directory_entry.text() or os.path.expanduser("~/Downloads")
            file_path = os.path.join(directory, self.file_list.currentItem().text())
            with open(file_path, "r", encoding="utf-8") as file:
                content = file.read()
            pyperclip.copy(content)

    def delete_file(self):
        if self.file_list.currentItem():
            directory = self.directory_entry.text() or os.path.expanduser("~/Downloads")
            file_path = os.path.join(directory, self.file_list.currentItem().text())
            os.remove(file_path)
            self.load_file_list()

if __name__ == '__main__':
    app = QApplication([])
    gui = WebScraperGUI()
    gui.show()
    app.exec_()

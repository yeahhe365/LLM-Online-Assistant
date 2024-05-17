import pyperclip
import datetime
import concurrent.futures
import requests
from bs4 import BeautifulSoup
import time
import os
import random
import logging
import re
from PyQt5.QtWidgets import (QApplication, QWidget, QLabel, QLineEdit, QPushButton,
                             QTextEdit, QVBoxLayout, QHBoxLayout, QMessageBox, QFileDialog,
                             QListWidget, QComboBox, QShortcut, QSpinBox)
from PyQt5.QtGui import QIcon, QFont, QPalette, QColor, QKeySequence
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QEvent

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# List of User-Agents to rotate through
USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/93.0.4577.82 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/85.0.4183.121 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:90.0) Gecko/20100101 Firefox/90.0',
    'Mozilla/5.0 (Windows NT 10.0; WOW64; Trident/7.0; rv:11.0) like Gecko',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_4) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/13.1 Safari/605.1.15'
]

MAX_WORKERS = 5

def get_random_user_agent():
    return random.choice(USER_AGENTS)

class ScrapingThread(QThread):
    progress_signal = pyqtSignal(str)
    finished_signal = pyqtSignal(str, int, int, int, int)

    def __init__(self, keywords, num_pages, search_engine, directory, question):
        super().__init__()
        self.keywords = keywords
        self.num_pages = num_pages
        self.search_engine = search_engine
        self.directory = directory
        self.question = question
        self._stop_event = False

    def run(self):
        all_results = []
        for keyword in self.keywords:
            if self._stop_event:
                break
            results = self.scrape_keyword(keyword)
            all_results.extend(results)

        file_path, words, chars_without_spaces, chars_with_spaces, non_chinese_words = self.save_results(all_results)
        with open(file_path, "r", encoding="utf-8") as file:
            content = file.read()
            pyperclip.copy(content)
        self.finished_signal.emit(file_path, words, chars_without_spaces, chars_with_spaces, non_chinese_words)

    def scrape_keyword(self, keyword):
        search_url = {
            "Google": f"https://www.google.com/search?q={keyword}",
            "Bing": f"https://www.bing.com/search?q={keyword}",
            "Baidu": f"https://www.baidu.com/s?wd={keyword}",
            "Sogou": f"https://www.sogou.com/web?query={keyword}"
        }.get(self.search_engine, f"https://www.google.com/search?q={keyword}")

        headers = {'User-Agent': get_random_user_agent()}
        response = requests.get(search_url, headers=headers)
        soup = BeautifulSoup(response.content, 'html.parser')

        search_results = {
            "Google": soup.select('div.g'),
            "Bing": soup.select('li.b_algo'),
            "Baidu": soup.select('div.result'),
            "Sogou": soup.select('div.vrwrap')
        }.get(self.search_engine, [])

        results = []
        for result in search_results:
            if self._stop_event:
                break
            link = result.select_one('a')
            if link and 'href' in link.attrs:
                url = link['href']
                title = link.get_text(strip=True)
                date = self.extract_date(result)
                results.append((keyword, title, date, url, ""))
            else:
                logging.warning(f"未找到有效链接: {result}")

        with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            text_results = list(executor.map(self.scrape_page, [url for _, _, _, url, _ in results]))

        for i, text in enumerate(text_results):
            results[i] = results[i][:4] + (text,)

        return results

    def extract_date(self, result):
        # Improved logic to extract the date from the search result
        if self.search_engine == "Google":
            date_tag = result.select_one('span.f')
            if date_tag:
                return date_tag.text
            else:
                # Another attempt to capture the date from different structure
                date_tag = result.select_one('span.st')
                if date_tag:
                    text = date_tag.get_text()
                    match = re.search(r'(\d{4}年\d{1,2}月\d{1,2}日|\d{4}-\d{2}-\d{2})', text)
                    if match:
                        return match.group(0)
        elif self.search_engine == "Bing":
            date_tag = result.select_one('span.news_dt')
            if date_tag:
                return date_tag.text
        elif self.search_engine == "Baidu":
            date_tag = result.select_one('.c-abstract')
            if date_tag:
                text = date_tag.get_text()
                match = re.search(r'(\d{4}-\d{2}-\d{2})', text)
                if match:
                    return match.group(0)
        elif self.search_engine == "Sogou":
            date_tag = result.select_one('.news-from')
            if date_tag:
                text = date_tag.get_text()
                match = re.search(r'(\d{4}-\d{2}-\d{2})', text)
                if match:
                    return match.group(0)
        return "未知日期"

    def scrape_page(self, url, retry_count=3):
        headers = {'User-Agent': get_random_user_agent()}
        for attempt in range(retry_count):
            if self._stop_event:
                break
            try:
                response = requests.get(url, headers=headers, timeout=30)
                response.raise_for_status()
                soup = BeautifulSoup(response.content, 'html.parser')
                paragraphs = soup.find_all('p')
                text = '\n'.join([p.get_text(strip=True) for p in paragraphs])
                return text
            except requests.exceptions.HTTPError as e:
                if e.response.status_code == 403:
                    logging.warning(f"403错误, 更换User-Agent重试请求: {url}")
                    headers['User-Agent'] = get_random_user_agent()
                    time.sleep(1)
                else:
                    logging.warning(f"请求失败 (尝试 {attempt + 1}/{retry_count}): {url}")
                    logging.warning(f"错误信息: {e}")
                    time.sleep(1)
            except requests.exceptions.RequestException as e:
                logging.warning(f"请求失败 (尝试 {attempt + 1}/{retry_count}): {url}")
                logging.warning(f"错误信息: {e}")
                time.sleep(1)
        logging.error(f"请求失败, 已达到最大重试次数: {url}")
        return ""

    def save_results(self, results):
        directory = self.directory or os.path.expanduser("~/Downloads")
        file_name = f"{self.question or self.keywords[0]}.txt"
        file_path = os.path.join(directory, file_name)

        base_name, ext = os.path.splitext(file_name)
        counter = 1
        while os.path.exists(file_path):
            file_path = os.path.join(directory, f"{base_name} ({counter}){ext}")
            counter += 1

        formatted_datetime = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(file_path, "w", encoding="utf-8") as file:
            file.write("您是一个知识渊博且乐于助人的人，可以回答任何问题。您的任务是回答以下由三个反引号分隔的问题。\n\n")
            file.write("问题:\n```\n{}\n```\n\n".format(self.question or self.keywords[0]))
            file.write("可能问题本身，或其中的一部分,需要从互联网获取相关信息才能给出令人满意的答案。下面由三个反引号分隔的相关搜索结果已经提供了必要的信息，用于为问题设置背景，因此您无需访问互联网来回答问题。\n\n")
            file.write(f"供您参考，今天的日期是{formatted_datetime}。\n\n")
            file.write("---\n\n")
            file.write("如果您在回答中使用了任何搜索结果，请始终在相应行的末尾引用来源，类似于Wikipedia.org引用信息。使用格式[[NUMBER](URL)], 其中NUMBER和URL对应于下面由三个反引号分隔的提供的搜索结果。\n\n")
            file.write("以清晰的格式呈现答案。\n")
            file.write("如果有必要, 使用编号列表以澄清事情。\n")
            file.write("尽量简洁回答，理想情况不超过1000个字。\n\n")
            file.write("---\n\n")
            file.write("如果在搜索结果中找不到足够的信息，不确定答案, 尽最大努力通过使用所有来自搜索结果的信息给出有帮助的回应。\n\n")
            file.write('"""\n')
            for i, (keyword, title, date, url, text) in enumerate(results, start=1):
                file.write(f"NUMBER: {i}\n")
                file.write(f"SEARCH ENGINE: {self.search_engine}\n")
                file.write(f"KEYWORD: {keyword}\n")
                file.write(f"URL: {url}\n")
                file.write(f"TITLE: {title}\n")
                file.write(f"DATE: {date}\n")
                file.write(f"CONTENT:\n{text}\n")
                file.write("\n\n")
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

class WebScraperGUI(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("LLM-Online-Assistant")
        self.setGeometry(100, 100, 800, 600)
        self.setWindowIcon(QIcon("icon.ico"))

        layout = QHBoxLayout()
        left_layout = QVBoxLayout()
        right_layout = QVBoxLayout()

        # 问题框布局
        question_layout = QHBoxLayout()
        question_label = QLabel("问题:", self)
        self.question_entry = QLineEdit(self)
        self.question_entry.setPlaceholderText("默认为关键词1")
        question_layout.addWidget(question_label)
        question_layout.addWidget(self.question_entry)
        left_layout.addLayout(question_layout)

        # 关键词框布局
        self.keywords_layout = QVBoxLayout()
        self.keyword_entries = []
        self.add_keyword_button = QPushButton("+", self)
        self.add_keyword_button.clicked.connect(self.add_keyword_entry)
        self.remove_keyword_button = QPushButton("-", self)
        self.remove_keyword_button.clicked.connect(self.remove_keyword_entry)

        # 显示关键词数量
        self.keywords_count_label = QLabel("关键词数量: 1", self)

        keyword_plus_layout = QHBoxLayout()
        keyword_plus_layout.addWidget(self.keywords_count_label)
        keyword_plus_label = QLabel("关键词:", self)
        keyword_plus_layout.addWidget(keyword_plus_label)
        keyword_plus_layout.addWidget(self.add_keyword_button)
        keyword_plus_layout.addWidget(self.remove_keyword_button)
        left_layout.addLayout(keyword_plus_layout)
        left_layout.addLayout(self.keywords_layout)
        self.add_keyword_entry()  # 添加第一个关键词输入框

        # 爬取页数布局
        num_pages_layout = QHBoxLayout()
        num_pages_label = QLabel("爬取页数:", self)
        self.num_pages_entry = QSpinBox(self)
        self.num_pages_entry.setRange(1, 100)
        self.num_pages_entry.setValue(10)  # 默认值为10
        num_pages_layout.addWidget(num_pages_label)

        num_pages_buttons_layout = QHBoxLayout()
        self.num_pages_add_button = QPushButton("+", self)
        self.num_pages_add_button.clicked.connect(self.increment_num_pages)
        self.num_pages_subtract_button = QPushButton("-", self)
        self.num_pages_subtract_button.clicked.connect(self.decrement_num_pages)

        num_pages_buttons_layout.addWidget(self.num_pages_add_button)
        num_pages_buttons_layout.addWidget(self.num_pages_subtract_button)
        num_pages_layout.addWidget(self.num_pages_entry)
        num_pages_layout.addLayout(num_pages_buttons_layout)
        left_layout.addLayout(num_pages_layout)

        # 搜索引擎布局
        search_engine_layout = QHBoxLayout()
        search_engine_label = QLabel("搜索引擎:", self)
        self.search_engine_combo = QComboBox(self)
        self.search_engine_combo.addItems(["Google", "Bing", "Baidu", "Sogou"])
        search_engine_layout.addWidget(search_engine_label)
        search_engine_layout.addWidget(self.search_engine_combo)
        left_layout.addLayout(search_engine_layout)

        # 导出目录布局
        directory_layout = QHBoxLayout()
        directory_label = QLabel("导出目录:", self)
        self.directory_entry = QLineEdit(self)
        self.directory_entry.setPlaceholderText("默认为下载文件夹")

        palette = QPalette()
        palette.setColor(QPalette.PlaceholderText, QColor(128, 128, 128))
        self.directory_entry.setPalette(palette)

        directory_button = QPushButton("浏览", self)
        directory_button.clicked.connect(self.browse_directory)
        directory_layout.addWidget(directory_label)
        directory_layout.addWidget(self.directory_entry)
        directory_layout.addWidget(directory_button)
        left_layout.addLayout(directory_layout)

        # 操作按钮布局
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

        # File list and management buttons
        file_management_layout = QVBoxLayout()
        file_buttons_layout = QHBoxLayout()
        self.copy_button = QPushButton("复制", self)
        self.copy_button.clicked.connect(self.copy_file)
        self.delete_button = QPushButton("删除", self)
        self.delete_button.clicked.connect(self.delete_file)
        file_buttons_layout.addWidget(self.copy_button)
        file_buttons_layout.addWidget(self.delete_button)
        file_management_layout.addLayout(file_buttons_layout)

        self.file_list = QListWidget(self)
        self.file_list.itemDoubleClicked.connect(self.open_file)
        file_management_layout.addWidget(self.file_list)
        right_layout.addLayout(file_management_layout)

        layout.addLayout(left_layout)
        layout.addLayout(right_layout)
        self.setLayout(layout)

        self.load_file_list()

        font = QFont()
        font.setPointSize(12)
        font.setBold(True)
        self.setFont(font)

        # Shortcuts for list operations
        self.delete_shortcut = QShortcut(QKeySequence("Delete"), self.file_list, self.delete_file)
        self.copy_shortcut = QShortcut(QKeySequence("Ctrl+C"), self.file_list, self.copy_file)

        # Ensure the first keyword and the question are synced
        self.sync_keyword_with_question()

    def increment_num_pages(self):
        current_value = self.num_pages_entry.value()
        self.num_pages_entry.setValue(current_value + 1)

    def decrement_num_pages(self):
        current_value = self.num_pages_entry.value()
        if current_value > 1:
            self.num_pages_entry.setValue(current_value - 1)

    def add_keyword_entry(self):
        if len(self.keyword_entries) < 10:  # Limit number of keywords to prevent UI overflow
            keyword_entry = QLineEdit(self)
            keyword_entry.setPlaceholderText(f"关键词 {len(self.keyword_entries) + 1}")
            keyword_entry.returnPressed.connect(self.keyword_enter_pressed)  # Enter键增加新的关键词
            
            palette = QPalette()
            palette.setColor(QPalette.PlaceholderText, QColor(128, 128, 128))
            keyword_entry.setPalette(palette)

            keyword_entry.installEventFilter(self)  # Install event filter for Backspace key handling

            self.keyword_entries.append(keyword_entry)
            self.keywords_layout.addWidget(keyword_entry)
            self.update_keyword_count()
            keyword_entry.setFocus()  # 将焦点转移到新的关键词框
        elif len(self.keyword_entries) == 10:
            self.add_keyword_button.setEnabled(False)

    def remove_keyword_entry(self):
        if len(self.keyword_entries) > 1:  # Ensure at least one keyword box is always present
            keyword_entry = self.keyword_entries.pop()
            self.keywords_layout.removeWidget(keyword_entry)
            keyword_entry.deleteLater()
            self.update_keyword_count()
            if len(self.keyword_entries) > 0:
                self.keyword_entries[-1].setFocus()  # Focus the last keyword box
        if len(self.keyword_entries) < 10:
            self.add_keyword_button.setEnabled(True)

    def start_scraping(self):
        keywords = [entry.text() for entry in self.keyword_entries if entry.text().strip()]
        if not keywords:
            QMessageBox.warning(self, "无关键词", "请至少输入一个关键词。")
            return

        num_pages = self.num_pages_entry.value()
        search_engine = self.search_engine_combo.currentText()
        directory = self.directory_entry.text()
        question = self.question_entry.text().strip() or (self.keyword_entries[0].text().strip() if self.keyword_entries else '')

        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.add_keyword_button.setEnabled(False)
        self.remove_keyword_button.setEnabled(False)
        for entry in self.keyword_entries:
            entry.setEnabled(False)
        self.num_pages_entry.setEnabled(False)
        self.search_engine_combo.setEnabled(False)
        self.directory_entry.setEnabled(False)
        self.question_entry.setEnabled(False)
        self.result_text.clear()
        self.status_label.setText("状态: 爬取中...")

        self.scraping_thread = ScrapingThread(keywords, num_pages, search_engine, directory, question)
        self.scraping_thread.progress_signal.connect(self.update_progress)
        self.scraping_thread.finished_signal.connect(self.scraping_finished)
        self.scraping_thread.start()

    def update_progress(self, message):
        # Update the GUI to show progress information
        self.status_label.setText(f"状态: {message}")

    def scraping_finished(self, file_path, words, chars_without_spaces, chars_with_spaces, non_chinese_words):
        # Handle the event after scraping is completed
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.add_keyword_button.setEnabled(True)
        self.remove_keyword_button.setEnabled(True)
        for entry in self.keyword_entries:
            entry.setEnabled(True)
        self.num_pages_entry.setEnabled(True)
        self.search_engine_combo.setEnabled(True)
        self.directory_entry.setEnabled(True)
        self.question_entry.setEnabled(True)

        # Update status label and result text
        self.status_label.setText("状态: 爬取完成")
        self.result_text.append(f"结果文件: {file_path}")
        self.result_text.append(f"总字数: {words}")
        self.result_text.append(f"字符数(不含空格): {chars_without_spaces}")
        self.result_text.append(f"字符数(含空格): {chars_with_spaces}")
        self.result_text.append(f"非中文单词数: {non_chinese_words}")
        
        # Reload the file list
        self.load_file_list()

    def stop_scraping(self):
        if hasattr(self, 'scraping_thread') and self.scraping_thread.isRunning():
            self.scraping_thread._stop_event = True
            self.scraping_thread.wait()
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.add_keyword_button.setEnabled(True)
        self.remove_keyword_button.setEnabled(True)
        for entry in self.keyword_entries:
            entry.setEnabled(True)
        self.num_pages_entry.setEnabled(True)
        self.search_engine_combo.setEnabled(True)
        self.directory_entry.setEnabled(True)
        self.question_entry.setEnabled(True)
        self.status_label.setText("状态: 已停止")

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
            with open(file_path, "r", encoding='utf-8') as file:
                content = file.read()
            pyperclip.copy(content)

    def delete_file(self):
        if self.file_list.currentItem():
            directory = self.directory_entry.text() or os.path.expanduser("~/Downloads")
            file_path = os.path.join(directory, self.file_list.currentItem().text())
            os.remove(file_path)
            self.load_file_list()

    def update_keyword_count(self):
        self.keywords_count_label.setText(f"关键词数量: {len(self.keyword_entries)}")

    def sync_keyword_with_question(self):
        # Adjust the logic to sync the question with the first keyword only when the question is empty
        if self.keyword_entries:
            self.keyword_entries[0].textChanged.connect(self.update_question_from_first_keyword)

    def update_question_from_first_keyword(self):
        if not self.question_entry.text().strip():  # Check if the question field is empty
            self.question_entry.setText(self.keyword_entries[0].text())

    def keyword_enter_pressed(self):
        # Check for Shift+Enter to add a new keyword entry
        if QApplication.keyboardModifiers() == Qt.ShiftModifier:
            self.add_keyword_entry()
        else:
            self.start_scraping()

    def eventFilter(self, source, event):
        if (event.type() == QEvent.KeyPress and source in self.keyword_entries):
            if event.key() == Qt.Key_Backspace and source.text() == "":
                self.remove_keyword_entry()
                return True
            elif event.key() == Qt.Key_Return and event.modifiers() & Qt.ShiftModifier:
                self.add_keyword_entry()
                return True
        return super(WebScraperGUI, self).eventFilter(source, event)

if __name__ == '__main__':
    app = QApplication([])
    gui = WebScraperGUI()
    gui.show()
    app.exec_()

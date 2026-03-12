import os
import time
import re
import subprocess
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException

# EXPORT_PATH - полный путь до вашей выгрузки Telegram чата. Например: 
#EXPORT_PATH = r"C:\Users\Admin\Downloads\Telegram Desktop\ChatExport_2026-03-12 (1)"
EXPORT_PATH = r"ВАШ_ПОЛНЫЙ_ПУТЬ_ДО_ДИРЕКТОРИИ"
MAX_URL = "https://web.max.ru/"

# Параметры батчевой отправки
BATCH_SIZE = 100
BATCH_DELAY = 5

def sanitize_text(text):
    """Удаляет символы вне BMP (эмодзи и редкие символы)"""
    cleaned = []
    for ch in text:
        if ord(ch) <= 0xFFFF or ch in '\n\r\t':
            cleaned.append(ch)
    return ''.join(cleaned)

def send_multiline_text(driver, input_field, text):
    """Отправка текстового сообщения с переносами строк"""
    try:
        text = sanitize_text(text)
        if not text.strip():
            print("⚠️ Пустое сообщение после очистки")
            return False

        input_field.send_keys(Keys.CONTROL + "a")
        input_field.send_keys(Keys.DELETE)
        time.sleep(0.2)

        lines = text.split('\n')
        for i, line in enumerate(lines):
            input_field.send_keys(line)
            if i < len(lines) - 1:
                input_field.send_keys(Keys.SHIFT + Keys.ENTER)
                time.sleep(0.1)
            else:
                input_field.send_keys(Keys.ENTER)

        time.sleep(1.2)
        return True
    except Exception as e:
        print(f"❌ Ошибка отправки текста: {str(e)[:100]}")
        return False

def copy_to_clipboard(file_path):
    """
    Копирует файл в буфер обмена Windows через PowerShell.
    Для изображений используется SetImage, для остальных SetFileDropList.
    """
    try:
        abs_path = os.path.abspath(file_path)
        ext = os.path.splitext(file_path)[1].lower()
        image_exts = ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp']

        if ext in image_exts:
            ps_script = f'''
            Add-Type -AssemblyName System.Windows.Forms
            $image = [System.Drawing.Image]::FromFile("{abs_path}")
            [System.Windows.Forms.Clipboard]::SetImage($image)
            '''
            print("   [Изображение] Копируем в буфер")
        else:
            ps_script = f'''
            Add-Type -AssemblyName System.Windows.Forms
            $files = New-Object System.Collections.Specialized.StringCollection
            $files.Add("{abs_path}")
            [System.Windows.Forms.Clipboard]::SetFileDropList($files)
            '''
            print("   [Файл] Копируем в буфер")

        result = subprocess.run(['powershell', '-command', ps_script],
                                capture_output=True, text=True)
        if result.returncode == 0:
            print("   ✅ Скопировано")
            return True
        else:
            print(f"   ⚠️ Ошибка PowerShell: {result.stderr}")
            return False
    except Exception as e:
        print(f"   ❌ Ошибка копирования: {e}")
        return False

def paste_from_clipboard(driver, input_field):
    """Вставляет содержимое буфера и отправляет (Ctrl+V, Enter)."""
    try:
        actions = ActionChains(driver)
        actions.click(input_field).perform()
        time.sleep(0.3)

        input_field.send_keys(Keys.CONTROL + "a")
        input_field.send_keys(Keys.DELETE)
        time.sleep(0.2)

        actions = ActionChains(driver)
        actions.key_down(Keys.CONTROL).send_keys('v').key_up(Keys.CONTROL).perform()
        time.sleep(2)  # ждём обработки вставки

        input_field.send_keys(Keys.ENTER)
        time.sleep(2)
        return True
    except Exception as e:
        print(f"   ❌ Ошибка вставки: {e}")
        return False

def send_media_via_clipboard(driver, input_field, file_path, caption=""):
    """Универсальная отправка любого медиа через буфер обмена."""
    try:
        print(f"   📎 Файл: {os.path.basename(file_path)}")
        if not copy_to_clipboard(file_path):
            return False
        time.sleep(0.5)
        if not paste_from_clipboard(driver, input_field):
            return False
        print("   ✅ Медиа отправлено")
        if caption.strip():
            time.sleep(1)
            print(f"   📝 Подпись: {caption[:50]}...")
            input_field.send_keys(Keys.CONTROL + "a")
            input_field.send_keys(Keys.DELETE)
            time.sleep(0.3)
            input_field.send_keys(sanitize_text(caption))
            input_field.send_keys(Keys.ENTER)
            print("   ✅ Подпись добавлена")
        return True
    except Exception as e:
        print(f"   ❌ Ошибка отправки медиа: {e}")
        return False

def extract_text_from_block(text_elem):
    """Извлекает текст из div с учётом тегов <br>."""
    if not text_elem:
        return ""
    parts = []
    for elem in text_elem.contents:
        if elem.name == 'br':
            parts.append('\n')
        elif elem.name:
            parts.append(elem.get_text())
        else:
            parts.append(str(elem).strip())
    return ''.join(parts).strip()

def extract_media_info(block, html_dir):
    """Извлекает информацию о медиа из блока сообщения."""
    media_items = []
    # Фото
    for link in block.find_all('a', class_=lambda x: x and 'photo_wrap' in x):
        href = link.get('href', '')
        if href and not href.startswith('http'):
            full = os.path.join(html_dir, href)
            media_items.append(('photo', full, ''))

    # Аудио
    for link in block.find_all('a', class_=lambda x: x and 'media_audio_file' in x):
        href = link.get('href', '')
        if href and not href.startswith('http'):
            full = os.path.join(html_dir, href)
            title_elem = link.find('div', class_='title bold')
            title = title_elem.get_text(strip=True) if title_elem else os.path.basename(href)
            media_items.append(('audio', full, title))

    # Видео
    for link in block.find_all('a', class_=lambda x: x and 'video_wrap' in x):
        href = link.get('href', '')
        if href and not href.startswith('http'):
            full = os.path.join(html_dir, href)
            media_items.append(('video', full, ''))

    return media_items

def parse_single_message(block, html_dir):
    """Парсит один блок сообщения, возвращает ('text', автор, текст) или ('media', автор, список медиа)."""
    try:
        if 'service' in block.get('class', []):
            return None

        author = ""
        author_elem = block.find('div', class_=lambda x: x and 'from_name' in x)
        if author_elem:
            author = author_elem.get_text(strip=True)

        media = extract_media_info(block, html_dir)
        if media:
            return ('media', author, media)

        text_elem = block.find('div', class_=lambda x: x and 'text' in x)
        if text_elem:
            text = extract_text_from_block(text_elem)
            text = re.sub(r'view-source:https?://[^\s<>]+', '', text)
            text = re.sub(r'file:///[^\s<>]+', '', text)
            text = text.strip()
            if text:
                return ('text', author, text)

        return None
    except Exception as e:
        print(f"⚠️ Ошибка парсинга сообщения: {e}")
        return None

def parse_telegram_messages(html_path):
    """Парсит HTML-файл экспорта Telegram, возвращает список сообщений."""
    print(f"📖 Парсим {os.path.basename(html_path)}...")
    html_dir = os.path.dirname(html_path)
    with open(html_path, 'r', encoding='utf-8') as f:
        soup = BeautifulSoup(f, 'html.parser')
    messages = []
    for block in soup.find_all('div', class_=lambda x: x and 'message default clearfix' in x):
        msg = parse_single_message(block, html_dir)
        if msg:
            messages.append(msg)
    print(f"   Найдено сообщений: {len(messages)}")
    return messages

def main():
    print("🚀 TG → MAX v10.1 (без смайлов, универсальный буфер)")
    print(f"📦 Настройки: BATCH_SIZE={BATCH_SIZE}, BATCH_DELAY={BATCH_DELAY}с")

    html_files = [f for f in os.listdir(EXPORT_PATH) if f.startswith('messages') and f.endswith('.html')]
    if not html_files:
        print(f"❌ Не найдены файлы messages*.html в {EXPORT_PATH}")
        return

    all_messages = []
    text_count = media_count = 0
    for f in html_files:
        msgs = parse_telegram_messages(os.path.join(EXPORT_PATH, f))
        for m in msgs:
            if m[0] == 'text':
                text_count += 1
            else:
                media_count += 1
        all_messages.extend(msgs)

    print(f"\n📊 Статистика: текстовых={text_count}, медиа-сообщений={media_count}")
    if not all_messages:
        print("❌ Нет сообщений для отправки")
        return

    # Настройка ChromeDriver
    options = Options()
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--start-maximized")
    driver = webdriver.Chrome(options=options)
    wait = WebDriverWait(driver, 15)

    try:
        print("\n🌐 Открываем MAX...")
        driver.get(MAX_URL)
        time.sleep(4)

        input("\n🔐 Отсканируйте QR-код, войдите, выберите чат 'Избранное' и нажмите Enter...")
        input("✅ Когда поле ввода будет активно, нажмите Enter...")

        input_field = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "div[role='textbox'], [contenteditable='true']")))
        print("✅ Поле ввода найдено")

        total = len(all_messages)
        print(f"\n🚀 Начинаем отправку {total} сообщений...")
        success = 0
        text_ok = media_ok = 0

        for i, msg in enumerate(all_messages):
            num = i+1
            typ, author, data = msg
            prefix = f"{author}: " if author else ""
            print(f"\n[{num}/{total}] ", end="")

            if typ == 'text':
                full = prefix + data
                print(f"📝 Текст: {full[:50]}...")
                if send_multiline_text(driver, input_field, full):
                    success += 1
                    text_ok += 1
                else:
                    print("❌ Ошибка")
            else:
                items = data
                print(f"📎 Медиа-сообщение ({len(items)} файлов)")
                for j, (mtype, path, caption) in enumerate(items, 1):
                    print(f"   [{j}/{len(items)}] ", end="")
                    # Поиск файла
                    if not os.path.exists(path):
                        base = os.path.basename(path)
                        for sub in ['photos', 'files']:
                            p = os.path.join(EXPORT_PATH, sub, base)
                            if os.path.exists(p):
                                path = p
                                break
                        else:
                            print(f"❌ Файл не найден: {path}")
                            continue

                    full_cap = (prefix + caption).strip()
                    type_label = "Фото" if mtype=='photo' else "Аудио" if mtype=='audio' else "Видео"
                    print(f"[{type_label}] {os.path.basename(path)}")

                    if send_media_via_clipboard(driver, input_field, path, full_cap):
                        success += 1
                        media_ok += 1
                        print(f"   ✅ Медиа {j}/{len(items)} отправлено")
                    else:
                        print(f"   ❌ Ошибка")

                    if j < len(items):
                        time.sleep(3)

            if num < total and num % BATCH_SIZE == 0:
                print(f"\n⏸️ Батч {num//BATCH_SIZE} завершен. Пауза {BATCH_DELAY}с...")
                time.sleep(BATCH_DELAY)
            else:
                time.sleep(2)

        print(f"\n{'='*50}\n🎉 ГОТОВО!\n{'='*50}")
        print(f"✅ Успешно отправлено: {success}/{total}")
        print(f"   - Текстовые: {text_ok}/{text_count}")
        print(f"   - Медиа: {media_ok}/{media_count}")

    except KeyboardInterrupt:
        print("\n⏹️ Прервано пользователем")
    except Exception as e:
        print(f"\n❌ Критическая ошибка: {e}")
    finally:
        input("\nНажмите Enter для закрытия браузера...")
        driver.quit()

if __name__ == "__main__":
    main()
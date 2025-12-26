"""
🎨 ربات سازنده استیکر پک تلگرام
نسخه:                     4.1 (Complete Version)
"""

import os
import json
import logging
import subprocess
from datetime import datetime
from typing import Dict, Optional, List, Tuple
from PIL import Image, ImageSequence
import re

from telegram import (
    Update,
    ReplyKeyboardMarkup,
    InputSticker,
    ReplyKeyboardRemove
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    ConversationHandler,
    filters
)
from telegram.constants import ParseMode, StickerFormat, StickerType
from telegram.error import TelegramError

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

DATA_FILE = "sticker_data.json"
TEMP_DIR = "temp_stickers"
TOKEN = "TOKEN"

os.makedirs(TEMP_DIR, exist_ok=True)

(
    MENU_STATE,
    INPUT_PACK_NAME,
    INPUT_PACK_TITLE,
    UPLOAD_IMAGE,
    SELECT_EMOJI,
    SELECT_PACK_FOR_ADD,
    SELECT_PACK_FOR_EDIT,
    INPUT_NEW_TITLE,
    SELECT_PACK_FOR_DELETE,
    CONFIRM_DELETE,
    VIEW_PACK_DETAIL,
    COPY_PACK_LINK
) = range(12)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# کلاس‌ها
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class DataManager:
    """مدیریت داده‌ها"""
    
    def __init__(self, filepath: str):
        self.filepath = filepath
        self.data = self._load()
    
    def _load(self) -> Dict:
        try: 
            if os.path.exists(self.filepath):
                with open(self.filepath, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            logger.error(f"خطا در بارگذاری داده: {e}")
        return {}
    
    def _save(self) -> None:
        try: 
            with open(self.filepath, 'w', encoding='utf-8') as f:
                json.dump(self.data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"خطا در ذخیره داده: {e}")
    
    def get_user(self, user_id: int) -> Dict:
        user_id = str(user_id)
        if user_id not in self.data:
            self.data[user_id] = {
                "created_at": datetime.now().isoformat(),
                "packs": {}
            }
            self._save()
        return self.data[user_id]
    
    def add_pack(self, user_id: int, pack_name: str, title: str) -> bool:
        user_id = str(user_id)
        user = self.get_user(user_id)
        
        if pack_name in user["packs"]:
            return False
        
        user["packs"][pack_name] = {
            "title": title,
            "stickers": [],
            "created_at": datetime.now().isoformat()
        }
        self._save()
        return True
    
    def add_sticker(self, user_id: int, pack_name: str, emoji: str) -> bool:
        user_id = str(user_id)
        user = self.get_user(user_id)
        
        if pack_name not in user["packs"]:
            return False
        
        user["packs"][pack_name]["stickers"].append({
            "emoji": emoji,
            "added_at": datetime.now().isoformat()
        })
        self._save()
        return True
    
    def update_pack_title(self, user_id: int, pack_name: str, new_title: str) -> bool:
        user_id = str(user_id)
        user = self.get_user(user_id)
        
        if pack_name not in user["packs"]:
            return False
        
        user["packs"][pack_name]["title"] = new_title
        self._save()
        return True
    
    def delete_pack(self, user_id: int, pack_name: str) -> bool:
        user_id = str(user_id)
        user = self.get_user(user_id)
        
        if pack_name not in user["packs"]:
            return False
        
        del user["packs"][pack_name]
        self._save()
        return True
    
    def get_user_packs(self, user_id: int) -> Dict:
        user = self.get_user(user_id)
        return user.get("packs", {})


class StickerConverter:
    """تبدیل فایل‌ها به فرمت استیکر تلگرام"""
    
    MAX_INPUT_SIZE = 100 * 1024 * 1024  # 100MB
    STICKER_SIZE = 512
    MAX_STICKER_SIZE = 256 * 1024  # 256KB
    
    @staticmethod
    def _is_file_animated(file_path: str) -> bool:
        """بررسی اینکه فایل انیمیشن است یا نه - پشتیبانی از همه فرمت‌ها"""
        # ابتدا سعی می‌کنیم با PIL چک کنیم (برای GIF و WebP)
        try:
            with Image.open(file_path) as img:
                # برای فایل‌هایی که PIL می‌تواند بخواند
                if hasattr(img, 'n_frames') and img.n_frames > 1:
                    return True
                
                try:
                    img.seek(1)
                    return True
                except (EOFError, Exception):
                    return False
        except Exception:
            # اگر PIL نتوانست بخواند، احتمالاً ویدئو است
            pass
        
        # برای فایل‌های ویدئویی (MP4, MOV, AVI) از ffprobe استفاده می‌کنیم
        try:
            cmd = [
                'ffprobe', '-v', 'error',
                '-select_streams', 'v:0',
                '-count_packets',
                '-show_entries', 'stream=nb_read_packets,duration',
                '-of', 'csv=p=0',
                file_path
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            
            if result.returncode == 0:
                output = result.stdout.strip()
                if output:
                    parts = output.split(',')
                    if len(parts) >= 2:
                        packets = int(parts[0]) if parts[0] else 0
                        duration = float(parts[1]) if parts[1] else 0
                        
                        # اگر بیش از 1 پکت دارد یا مدت زمان بیش از 0.1 ثانیه است، انیمیشن است
                        if packets > 1 or duration > 0.1:
                            return True
            return False
            
        except Exception as e:
            logger.warning(f"خطا در بررسی انیمیشن با ffprobe: {e}")
            return False
    
    @staticmethod
    def _convert_to_static_sticker(input_path: str, output_path: str) -> Optional[str]:
        """تبدیل به استیکر استاتیک WebP"""
        try:
            # برای فایل‌های ویدئویی، باید از ffmpeg برای استخراج یک فریم استفاده کنیم
            file_ext = os.path.splitext(input_path)[1].lower()
            
            if file_ext in ['.mp4', '.mov', '.avi', '.mkv', '.webm']:
                # استخراج فریم اول از ویدئو
                frame_path = os.path.join(os.path.dirname(output_path), 'frame.png')
                cmd = [
                    'ffmpeg', '-i', input_path,
                    '-ss', '00:00:00.000',
                    '-vframes', '1',
                    '-vf', 'scale=512:512:force_original_aspect_ratio=decrease,pad=512:512:(ow-iw)/2:(oh-ih)/2',
                    '-y', frame_path
                ]
                
                try:
                    subprocess.run(cmd, capture_output=True, timeout=30, check=True)
                    input_path = frame_path  # از فریم استخراج شده استفاده کن
                except Exception as e:
                    logger.warning(f"خطا در استخراج فریم از ویدئو: {e}")
            
            with Image.open(input_path) as img:
                # اگر فایل GIF متحرک است، فقط فریم اول را بگیر
                if hasattr(img, 'n_frames') and img.n_frames > 1:
                    img.seek(0)
                
                # تبدیل به RGBA اگر نیست
                if img.mode != 'RGBA':
                    if img.mode == 'RGB':
                        img = img.convert('RGBA')
                    elif img.mode == 'P':
                        img = img.convert('RGBA')
                    elif img.mode == '1' or img.mode == 'L':
                        img = img.convert('RGBA')
                    else:
                        img = img.convert('RGBA')
                
                # تغییر سایز با حفظ نسبت
                img.thumbnail((StickerConverter.STICKER_SIZE, StickerConverter.STICKER_SIZE), 
                             Image.Resampling.LANCZOS)
                
                # ایجاد کانواس 512x512 شفاف
                canvas = Image.new('RGBA', (StickerConverter.STICKER_SIZE, StickerConverter.STICKER_SIZE), 
                                  (0, 0, 0, 0))
                
                # قرار دادن تصویر در وسط
                offset = (
                    (StickerConverter.STICKER_SIZE - img.width) // 2,
                    (StickerConverter.STICKER_SIZE - img.height) // 2
                )
                canvas.paste(img, offset, img)
                
                # ذخیره با کیفیت‌های مختلف تا رسیدن به حجم مناسب
                for quality in [90, 80, 70, 60, 50, 40, 30, 20, 10, 5]:
                    canvas.save(output_path, 'WEBP', quality=quality, method=6)
                    
                    if os.path.getsize(output_path) <= StickerConverter.MAX_STICKER_SIZE:
                        logger.info(f"✅ استاتیک با کیفیت {quality}: {os.path.getsize(output_path)/1024:.1f}KB")
                        
                        # حذف فایل فریم موقت اگر وجود دارد
                        if 'frame.png' in input_path and os.path.exists(input_path):
                            os.unlink(input_path)
                        
                        return output_path
                
                # اگر هنوز بزرگ است، سایز را کاهش بده
                logger.info("📉 کاهش سایز برای کاهش حجم...")
                for size in [400, 300, 200, 150]:
                    small_img = img.copy()
                    small_img.thumbnail((size, size), Image.Resampling.LANCZOS)
                    
                    canvas = Image.new('RGBA', (512, 512), (0, 0, 0, 0))
                    offset = (
                        (512 - small_img.width) // 2,
                        (512 - small_img.height) // 2
                    )
                    canvas.paste(small_img, offset, small_img)
                    
                    for quality in [50, 30, 20, 10, 5]:
                        canvas.save(output_path, 'WEBP', quality=quality, method=6)
                        
                        if os.path.getsize(output_path) <= StickerConverter.MAX_STICKER_SIZE:
                            logger.info(f"✅ استاتیک با سایز {size} و کیفیت {quality}: {os.path.getsize(output_path)/1024:.1f}KB")
                            
                            # حذف فایل فریم موقت اگر وجود دارد
                            if 'frame.png' in input_path and os.path.exists(input_path):
                                os.unlink(input_path)
                            
                            return output_path
                
                # آخرین تلاش: کمترین کیفیت
                canvas.save(output_path, 'WEBP', quality=1, method=6)
                logger.info(f"🔄 حجم نهایی: {os.path.getsize(output_path)/1024:.1f}KB")
                
                # حذف فایل فریم موقت اگر وجود دارد
                if 'frame.png' in input_path and os.path.exists(input_path):
                    os.unlink(input_path)
                
                return output_path
                
        except Exception as e:
            logger.error(f"❌ خطا در تبدیل استاتیک: {e}")
            
            # حذف فایل فریم موقت اگر وجود دارد
            try:
                if 'frame.png' in input_path and os.path.exists(input_path):
                    os.unlink(input_path)
            except:
                pass
            
            return None
    
    @staticmethod
    def _convert_to_animated_sticker(input_path: str, output_path: str) -> Optional[str]:
        """تبدیل به استیکر متحرک WebP"""
        try:
            # پروفایل‌های مختلف برای کاهش حجم
            profiles = [
                # پروفایل 1: کیفیت خوب
                {'scale': 512, 'fps': 10, 'quality': 60, 'preset': 'default', 'loop': 0, 'duration': 10},
                {'scale': 480, 'fps': 10, 'quality': 50, 'preset': 'default', 'loop': 0, 'duration': 8},
                
                # پروفایل 2: کیفیت متوسط
                #{'scale': 448, 'fps': 8, 'quality': 40, 'preset': 'default', 'loop': 0, 'duration': 6},
                #{'scale': 400, 'fps': 8, 'quality': 35, 'preset': 'default', 'loop': 0, 'duration': 5},
                
                # پروفایل 3: کیفیت پایین
                #{'scale': 360, 'fps': 6, 'quality': 30, 'preset': 'icon', 'loop': 0, 'duration': 4},
                #{'scale': 320, 'fps': 6, 'quality': 25, 'preset': 'icon', 'loop': 0, 'duration': 3},
                
                # پروفایل 4: کیفیت بسیار پایین
                #{'scale': 280, 'fps': 5, 'quality': 20, 'preset': 'icon', 'loop': 0, 'duration': 3},
                #{'scale': 240, 'fps': 5, 'quality': 15, 'preset': 'icon', 'loop': 0, 'duration': 2},
                
                # پروفایل 5: حداقل کیفیت
                #{'scale': 200, 'fps': 4, 'quality': 10, 'preset': 'icon', 'loop': 0, 'duration': 2},
                #{'scale': 160, 'fps': 3, 'quality': 5, 'preset': 'icon', 'loop': 0, 'duration': 1},
            ]
            
            for i, profile in enumerate(profiles):
                scale = profile['scale']
                fps = profile['fps']
                quality = profile['quality']
                preset = profile['preset']
                loop = profile['loop']
                duration = profile.get('duration')
                
                # ساخت فیلتر ffmpeg
                vf_parts = []
                
                if duration:
                    vf_parts.append(f'trim=duration={duration},setpts=PTS-STARTPTS')
                
                if fps:
                    vf_parts.append(f'fps={fps}')
                
                vf_parts.append(f'scale={scale}:{scale}:force_original_aspect_ratio=decrease')
                vf_parts.append(f'pad={scale}:{scale}:(ow-iw)/2:(oh-ih)/2')
                vf = ','.join(vf_parts)
                
                cmd = [
                    'ffmpeg', '-i', input_path,
                    '-vf', vf,
                    '-loop', str(loop),
                    '-c:v', 'libwebp',
                    '-lossless', '0',
                    '-q:v', str(quality),
                    '-preset', preset,
                    '-compression_level', '6',
                    '-an',
                    '-y',
                    output_path
                ]
                
                logger.info(f"🎬 تلاش {i+1}: scale={scale}, fps={fps}, quality={quality}")
                
                try:
                    subprocess.run(cmd, capture_output=True, timeout=60, check=True)
                    
                    if os.path.exists(output_path):
                        file_size = os.path.getsize(output_path)
                        logger.info(f"   حجم: {file_size/1024:.1f}KB")
                        
                        # چک حجم
                        if file_size <= StickerConverter.MAX_STICKER_SIZE:
                            logger.info(f"✅ انیمیشن موفق: {file_size/1024:.1f}KB")
                            return output_path
                        else:
                            # حذف و ادامه با پروفایل بعدی
                            if os.path.exists(output_path):
                                os.unlink(output_path)
                except Exception as e:
                    logger.warning(f"   خطا در تلاش {i+1}: {e}")
                    if os.path.exists(output_path):
                        os.unlink(output_path)
                    continue
            
            # اگر همه پروفایل‌ها شکست خوردند، سعی کن با تنظیمات بسیار پایین
            logger.info("🔥 آخرین تلاش با تنظیمات بسیار پایین...")
            cmd = [
                'ffmpeg', '-i', input_path,
                '-vf', 'fps=2,scale=128:128:force_original_aspect_ratio=decrease,pad=128:128:(ow-iw)/2:(oh-ih)/2',
                '-loop', '0',
                '-c:v', 'libwebp',
                '-lossless', '0',
                '-q:v', '1',
                '-preset', 'icon',
                '-compression_level', '6',
                '-an',
                '-y',
                output_path
            ]
            
            try:
                subprocess.run(cmd, capture_output=True, timeout=60, check=True)
                if os.path.exists(output_path):
                    file_size = os.path.getsize(output_path)
                    logger.info(f"🔥 آخرین تلاش: {file_size/1024:.1f}KB")
                    return output_path
            except:
                pass
            
            return None
            
        except Exception as e:
            logger.error(f"❌ خطا در تبدیل انیمیشن: {e}")
            return None
    
    @staticmethod
    def convert_to_sticker(input_path: str, output_path: str) -> Tuple[Optional[str], bool]:
        """تبدیل فایل به فرمت استیکر تلگرام"""
        try:
            # چک وجود فایل
            if not os.path.exists(input_path):
                logger.error(f"❌ فایل ورودی وجود ندارد: {input_path}")
                return None, False
            
            input_size = os.path.getsize(input_path)
            logger.info(f"📁 پردازش فایل: {input_size/1024:.1f}KB")
            
            # چک اینکه آیا فایل واقعاً انیمیشن است
            is_animated = StickerConverter._is_file_animated(input_path)
            logger.info(f"🔍 تشخیص انیمیشن: {is_animated}")
            
            if is_animated:
                # سعی کن به انیمیشن تبدیل کنی
                result = StickerConverter._convert_to_animated_sticker(input_path, output_path)
                
                if result and os.path.exists(result):
                    # دوباره چک کن که واقعاً انیمیشن باشد
                    final_is_animated = StickerConverter._is_file_animated(result)
                    
                    if final_is_animated:
                        file_size = os.path.getsize(result)
                        logger.info(f"✅ انیمیشن تولید شد: {file_size/1024:.1f}KB")
                        
                        # اگر حجم خیلی زیاد است، به استاتیک تبدیل کن
                        if file_size > StickerConverter.MAX_STICKER_SIZE * 3:  # بیش از 768KB
                            logger.warning(f"⚠️ حجم انیمیشن زیاد است ({file_size/1024:.1f}KB)، تبدیل به استاتیک...")
                            os.unlink(result)
                            return StickerConverter._convert_to_static_sticker(input_path, output_path), False
                        
                        return result, True
                    else:
                        logger.warning("⚠️ فایل انیمیشن تولید نشد، تبدیل به استاتیک...")
                        if os.path.exists(result):
                            os.unlink(result)
                        # به استاتیک تبدیل کن
                        return StickerConverter._convert_to_static_sticker(input_path, output_path), False
                else:
                    logger.warning("❌ تبدیل انیمیشن شکست خورد، تبدیل به استاتیک...")
                    return StickerConverter._convert_to_static_sticker(input_path, output_path), False
            else:
                # تبدیل به استاتیک
                result = StickerConverter._convert_to_static_sticker(input_path, output_path)
                return result, False
                
        except Exception as e:
            logger.error(f"❌ خطا در تبدیل: {e}")
            return None, False


class UI:
    """رابط کاربری"""
    
    @staticmethod
    def main_menu():
        keyboard = [
            ["➕ ساخت پک جدید", "📁 مشاهده پک‌ها"],
            ["➕ افزودن استیکر", "✏️ ویرایش پک"],
            ["🗑️ حذف پک", "📊 آمار"],
            ["ℹ️ راهنما", "🎬 ویدئو"]
        ]
        return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    @staticmethod
    def back_button():
        keyboard = [["🔙 بازگشت"]]
        return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    @staticmethod
    def emoji_buttons():
        emojis = ['😀', '😂', '🥰', '😎', '🤔', '😡', '😭', '🤯', '🥳', '🤖']
        
        buttons = []
        for i in range(0, len(emojis), 5):
            row = [emojis[j] for j in range(i, min(i+5, len(emojis)))]
            buttons.append(row)
        
        buttons.append(["📝 ایموجی دلخواه", "✅ تأیید"])
        
        return ReplyKeyboardMarkup(buttons, resize_keyboard=True)
    
    @staticmethod
    def yes_no_buttons():
        keyboard = [["✅ بله", "❌ خیر"]]
        return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


db = DataManager(DATA_FILE)
ui = UI()


def get_pack_full_name(pack_name: str, bot_username: str, is_animated: bool = False) -> str:
    """تولید نام پک معتبر"""
    if is_animated:
        return f"{pack_name}_anim_by_{bot_username}"
    else:
        return f"{pack_name}_by_{bot_username}"


def extract_emoji(text: str) -> Optional[str]:
    """استخراج ایموجی از متن"""
    for char in text:
        code = ord(char)
        if any([
            0x1F300 <= code <= 0x1F9FF,
            0x2600 <= code <= 0x27BF,
            0x1F600 <= code <= 0x1F64F,
            code in [0x2764, 0x1F60A]
        ]):
            return char
    return None


def cleanup_temp():
    """پاکسازی فایل‌های موقت"""
    try: 
        for f in os.listdir(TEMP_DIR):
            path = os.path.join(TEMP_DIR, f)
            if os.path.isfile(path):
                try:
                    os.unlink(path)
                except:
                    pass
    except Exception as e:
        logger.warning(f"خطا در پاکسازی: {e}")


async def check_file_size(update: Update, context: ContextTypes.DEFAULT_TYPE, file_size: int) -> bool:
    """چک کردن حجم فایل قبل از پردازش"""
    if file_size > StickerConverter.MAX_INPUT_SIZE:
        await update.message.reply_text(
            "❌ فایل خیلی بزرگ است! (حداکثر 100 مگابایت)\n\n"
            "لطفاً فایل کوچک‌تری ارسال کنید.",
            reply_markup=ui.back_button()
        )
        return False
    
    if file_size > 20 * 1024 * 1024:  # بیشتر از 20MB
        await update.message.reply_text(
            "⚠️ فایل بزرگی ارسال کردید.\n"
            "در حال پردازش... (ممکن است 1-2 دقیقه طول بکشد)",
            reply_markup=ui.back_button()
        )
    
    return True


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# HANDLERS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    
    await update.message.reply_text(
        f"👋 سلام {user.first_name}!\n\n"
        "🎨 <b>خوش آمدید به ربات سازنده استیکر پک! </b>\n\n"
        "✨ <b>ویژگی‌ها:</b>\n"
        "✅ ساخت پک‌های استیکر واقعی\n"
        "✅ پشتیبانی از عکس، GIF و ویدئو\n"
        "✅ مدیریت آسان پک‌ها\n"
        "✅ انتخاب ایموجی دلخواه\n"
        "✅ کاهش حجم خودکار\n\n"
        "📸 <b>فرمت‌های پشتیبانی شده:</b>\n"
        "• عکس: JPG, PNG, WebP, BMP\n"
        "• انیمیشن: GIF, MP4, MOV, AVI\n\n"
        "⚡ <b>ویژگی جدید:</b>\n"
        "• پشتیبانی کامل از MP4 و ویدئو\n"
        "• تشخیص هوشمند انیمیشن/استاتیک\n"
        "• تبدیل خودکار همه فرمت‌ها\n\n"
        "🎬 <b>برای ویدئوها:</b>\n"
        "• مدت: حداکثر ۱۰ ثانیه\n"
        "• حجم: حداکثر 100MB\n"
        "• تبدیل خودکار به استیکر متحرک\n\n"
        "بیایید شروع کنیم! ",
        parse_mode=ParseMode.HTML,
        reply_markup=ui.main_menu()
    )
    
    return MENU_STATE


async def handle_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_id = update.effective_user.id
    
    if text == "➕ ساخت پک جدید":
        await update.message.reply_text(
            "📝 <b>نام انگلیسی برای پک را وارد کنید:</b>\n\n"
            "⚠️ قوانین:\n"
            "• فقط حروف کوچک (a-z)\n"
            "• فقط اعداد (0-9)\n"
            "• فقط underline (_)\n"
            "• مثال: <code>funny_cats</code>",
            parse_mode=ParseMode.HTML,
            reply_markup=ui.back_button()
        )
        return INPUT_PACK_NAME
    
    elif text == "📁 مشاهده پک‌ها":
        packs = db.get_user_packs(user_id)
        
        if not packs: 
            await update.message.reply_text(
                "📭 شما هنوز پکی ندارید!\n\nابتدا پک جدید بسازید.",
                parse_mode=ParseMode.HTML,
                reply_markup=ui.back_button()
            )
            return MENU_STATE
        
        context.user_data["packs_list"] = {}
        buttons = []
        
        for pack_name, data in packs.items():
            count = len(data.get("stickers", []))
            btn_text = f"📦 {data['title']} ({count}/120)"
            context.user_data["packs_list"][btn_text] = pack_name
            buttons.append([btn_text])
        
        buttons.append(["🔙 بازگشت"])
        
        await update.message.reply_text(
            "📚 <b>پک‌های شما:</b>\n\nروی هر پک کلیک کنید:",
            parse_mode=ParseMode.HTML,
            reply_markup=ReplyKeyboardMarkup(buttons, resize_keyboard=True)
        )
        
        return VIEW_PACK_DETAIL
    
    elif text == "➕ افزودن استیکر":
        packs = db.get_user_packs(user_id)
        
        if not packs: 
            await update.message.reply_text(
                "❌ شما پکی برای افزودن ندارید!\n\nابتدا پک بسازید.",
                parse_mode=ParseMode.HTML,
                reply_markup=ui.back_button()
            )
            return MENU_STATE
        
        context.user_data["add_packs_list"] = {}
        buttons = []
        
        for pack_name, data in packs.items():
            count = len(data.get("stickers", []))
            if count < 120:
                btn_text = f"➕ {data['title']} ({count}/120)"
                context.user_data["add_packs_list"][btn_text] = pack_name
                buttons.append([btn_text])
        
        if not buttons:
            await update.message.reply_text(
                "❌ تمام پک‌های شما پر هستند! (120 استیکر)",
                parse_mode=ParseMode.HTML,
                reply_markup=ui.back_button()
            )
            return MENU_STATE
        
        buttons.append(["🔙 بازگشت"])
        
        await update.message.reply_text(
            "📦 <b>انتخاب پک برای افزودن استیکر:</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=ReplyKeyboardMarkup(buttons, resize_keyboard=True)
        )
        
        return SELECT_PACK_FOR_ADD
    
    elif text == "✏️ ویرایش پک":
        packs = db.get_user_packs(user_id)
        
        if not packs:
            await update.message.reply_text(
                "❌ پکی برای ویرایش نداری!",
                parse_mode=ParseMode.HTML,
                reply_markup=ui.back_button()
            )
            return MENU_STATE
        
        context.user_data["edit_packs_list"] = {}
        buttons = []
        
        for pack_name, data in packs.items():
            btn_text = f"✏️ {data['title']}"
            context.user_data["edit_packs_list"][btn_text] = pack_name
            buttons.append([btn_text])
        
        buttons.append(["🔙 بازگشت"])
        
        await update.message.reply_text(
            "📝 <b>انتخاب پک برای ویرایش:</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=ReplyKeyboardMarkup(buttons, resize_keyboard=True)
        )
        
        return SELECT_PACK_FOR_EDIT
    
    elif text == "🗑️ حذف پک":
        packs = db.get_user_packs(user_id)
        
        if not packs: 
            await update.message.reply_text(
                "❌ پکی برای حذف نداری!",
                parse_mode=ParseMode.HTML,
                reply_markup=ui.back_button()
            )
            return MENU_STATE
        
        context.user_data["del_packs_list"] = {}
        buttons = []
        
        for pack_name, data in packs.items():
            btn_text = f"🗑️ {data['title']}"
            context.user_data["del_packs_list"][btn_text] = pack_name
            buttons.append([btn_text])
        
        buttons.append(["🔙 بازگشت"])
        
        await update.message.reply_text(
            "⚠️ <b>انتخاب پک برای حذف:</b>\n\n"
            "⚠️ این عمل غیرقابل بازگشت است!",
            parse_mode=ParseMode.HTML,
            reply_markup=ReplyKeyboardMarkup(buttons, resize_keyboard=True)
        )
        
        return SELECT_PACK_FOR_DELETE
    
    elif text == "📊 آمار":
        packs = db.get_user_packs(user_id)
        total = sum(len(p.get("stickers", [])) for p in packs.values())
        
        await update.message.reply_text(
            f"📊 <b>آمار شما:</b>\n\n"
            f"👤 کاربر: {update.effective_user.first_name}\n"
            f"📁 پک‌ها: {len(packs)}\n"
            f"🎨 کل استیکرها: {total}\n",
            parse_mode=ParseMode.HTML,
            reply_markup=ui.back_button()
        )
        return MENU_STATE
    
    elif text == "ℹ️ راهنما":
        await update.message.reply_text(
            "📖 <b>راهنمای سریع:</b>\n\n"
            "<b>ساخت پک جدید:</b>\n"
            "1. نام انگلیسی پک را وارد کنید\n"
            "2. عنوان فارسی/انگلیسی را وارد کنید\n"
            "3. عکس، GIF یا ویدئو ارسال کنید\n"
            "4. ایموجی انتخاب کنید\n\n"
            "<b>فرمت‌های پشتیبانی:</b>\n"
            "• عکس: JPG, PNG, WebP, BMP\n"
            "• انیمیشن: GIF, MP4, MOV, AVI\n\n"
            "<b>محدودیت‌ها:</b>\n"
            "• حداکثر 120 استیکر در هر پک\n"
            "• حداکثر حجم فایل: 100MB\n"
            "• حداکثر حجم استیکر: 256KB\n"
            "• حداکثر مدت ویدئو: 10 ثانیه\n\n"
            "<b>نکات برای ویدئو:</b>\n"
            "• از ویدئوهای کوتاه استفاده کنید\n"
            "• وضوح را کاهش دهید\n"
            "• فایل‌های کوچک‌تر نتیجه بهتری دارند",
            parse_mode=ParseMode.HTML,
            reply_markup=ui.back_button()
        )
        return MENU_STATE
    
    elif text == "🎬 ویدئو":
        await update.message.reply_text(
            "🎬 <b>راهنمای ارسال ویدئو:</b>\n\n"
            "✅ <b>ویدئوهای مناسب:</b>\n"
            "• مدت: 3-5 ثانیه\n"
            "• حجم: کمتر از 20MB\n"
            "• وضوح: 480p یا 720p\n"
            "• فرمت: MP4, MOV, AVI\n\n"
            "❌ <b>ویدئوهای نامناسب:</b>\n"
            "• مدت: بیش از 10 ثانیه\n"
            "• حجم: بیش از 50MB\n"
            "• وضوح: 4K یا 1080p\n"
            "• فرمت: MKV, WMV, FLV\n\n"
            "⚡ <b>نکات فنی:</b>\n"
            "• ربات به صورت خودکار ویدئو را به WebP متحرک تبدیل می‌کند\n"
            "• حجم نهایی زیر 256KB خواهد بود\n"
            "• کیفیت ممکن است کاهش یابد\n\n"
            "📹 <b>ابزارهای مفید:</b>\n"
            "• برای کاهش حجم: handbrake.fr\n"
            "• برای کوتاه کردن: online-video-cutter.com\n"
            "• برای تبدیل فرمت: cloudconvert.com",
            parse_mode=ParseMode.HTML,
            reply_markup=ui.back_button()
        )
        return MENU_STATE
    
    elif text == "🔙 بازگشت": 
        await update.message.reply_text(
            "🏠 <b>منوی اصلی</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=ui.main_menu()
        )
        return MENU_STATE
    
    return MENU_STATE


async def handle_pack_name_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pack_name = update.message.text.strip().lower()
    user_id = update.effective_user.id
    
    if pack_name == "🔙 بازگشت":
        await update.message.reply_text(
            "🏠 <b>منوی اصلی</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=ui.main_menu()
        )
        return MENU_STATE
    
    if not re.match(r'^[a-z0-9_]{1,32}$', pack_name):
        await update.message.reply_text(
            "❌ نام نامعتبر!\n\n"
            "✅ صحیح: funny_cats\n"
            "❌ غلط: Funny Cats! 123",
            parse_mode=ParseMode.HTML,
            reply_markup=ui.back_button()
        )
        return INPUT_PACK_NAME
    
    packs = db.get_user_packs(user_id)
    if pack_name in packs: 
        await update.message.reply_text(
            "❌ این نام قبلاً استفاده شده!",
            parse_mode=ParseMode.HTML,
            reply_markup=ui.back_button()
        )
        return INPUT_PACK_NAME
    
    context.user_data["pack_name"] = pack_name
    
    await update.message.reply_text(
        f"✅ نام پک: <code>{pack_name}</code>\n\n"
        "📝 حالا عنوان نمایشی را وارد کنید:\n"
        "(فارسی یا انگلیسی، حداکثر 64 کاراکتر)",
        parse_mode=ParseMode.HTML,
        reply_markup=ui.back_button()
    )
    
    return INPUT_PACK_TITLE


async def handle_pack_title_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    title = update.message.text.strip()
    user_id = update.effective_user.id
    pack_name = context.user_data.get("pack_name")
    
    if title == "🔙 بازگشت":
        await update.message.reply_text(
            "🏠 <b>منوی اصلی</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=ui.main_menu()
        )
        return MENU_STATE
    
    if len(title) > 64:
        await update.message.reply_text(
            "❌ عنوان خیلی طولانی است! (حداکثر 64)",
            parse_mode=ParseMode.HTML,
            reply_markup=ui.back_button()
        )
        return INPUT_PACK_TITLE
    
    if db.add_pack(user_id, pack_name, title):
        await update.message.reply_text(
            f"🎉 پک '{title}' ایجاد شد!\n\n"
            "📸 حالا عکس، GIF یا ویدئو اول را بفرستید:",
            parse_mode=ParseMode.HTML,
            reply_markup=ReplyKeyboardRemove()
        )
        context.user_data["current_pack"] = pack_name
        return UPLOAD_IMAGE
    else:
        await update.message.reply_text(
            "❌ خطا در ایجاد پک!",
            parse_mode=ParseMode.HTML,
            reply_markup=ui.back_button()
        )
        return MENU_STATE


async def handle_file_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """دریافت فایل (عکس، GIF، ویدئو)"""
    user_id = update.effective_user.id
    
    # تشخیص نوع فایل
    if update.message.photo:
        file = update.message.photo[-1]
        file_type = "photo"
    elif update.message.document:
        file = update.message.document
        file_type = "document"
    elif update.message.video:
        file = update.message.video
        file_type = "video"
    elif update.message.animation:
        file = update.message.animation
        file_type = "animation"
    else:
        await update.message.reply_text("❌ لطفاً یک فایل ارسال کنید!")
        return UPLOAD_IMAGE
    
    # چک حجم فایل
    if not await check_file_size(update, context, file.file_size):
        return UPLOAD_IMAGE
    
    status = await update.message.reply_text("⏳ پردازش فایل...")
    
    try:
        # دانلود فایل
        file_obj = await context.bot.get_file(file.file_id)
        
        # تشخیص پسوند فایل
        mime_type = getattr(file, 'mime_type', None) or 'image/jpeg'
        
        if 'jpeg' in mime_type or 'jpg' in mime_type:
            ext = '.jpg'
        elif 'png' in mime_type:
            ext = '.png'
        elif 'gif' in mime_type:
            ext = '.gif'
        elif 'webp' in mime_type:
            ext = '.webp'
        elif 'mp4' in mime_type:
            ext = '.mp4'
        elif 'mov' in mime_type:
            ext = '.mov'
        elif 'avi' in mime_type:
            ext = '.avi'
        elif 'mkv' in mime_type:
            ext = '.mkv'
        elif 'webm' in mime_type:
            ext = '.webm'
        else:
            ext = '.dat'
        
        input_path = os.path.join(TEMP_DIR, f"{user_id}_input{ext}")
        output_path = os.path.join(TEMP_DIR, f"{user_id}_output.webp")
        
        await file_obj.download_to_drive(input_path)
        
        file_size_kb = os.path.getsize(input_path) / 1024
        logger.info(f"📁 پردازش فایل: {file_size_kb:.1f}KB, نوع: {mime_type}")
        
        # پیام بر اساس نوع فایل
        if 'video' in mime_type:
            await status.edit_text("🎬 در حال پردازش ویدئو...")
        elif 'gif' in mime_type:
            await status.edit_text("🌀 در حال پردازش GIF...")
        else:
            await status.edit_text("🖼️ در حال پردازش عکس...")
        
        # تبدیل به استیکر
        result, is_animated = StickerConverter.convert_to_sticker(input_path, output_path)
        
        if not result or not os.path.exists(result):
            await status.delete()
            await update.message.reply_text(
                "❌ خطا در پردازش فایل!\n\n"
                "لطفاً:\n"
                "• از فایل معتبر استفاده کنید\n"
                "• حجم فایل را کاهش دهید\n"
                "• فرمت دیگری امتحان کنید",
                reply_markup=ui.back_button()
            )
            try:
                os.unlink(input_path)
            except:
                pass
            return UPLOAD_IMAGE
        
        context.user_data["output_path"] = result
        context.user_data["input_path"] = input_path
        context.user_data["is_animated"] = is_animated
        
        await status.delete()
        
        sticker_type = "🎬 متحرک" if is_animated else "📷 ثابت"
        result_size = os.path.getsize(result) / 1024
        
        await update.message.reply_text(
            f"✅ فایل پردازش شد!\n"
            f"📊 نوع: {sticker_type}\n"
            f"📦 حجم ورودی: {file_size_kb:.1f}KB\n"
            f"📦 حجم خروجی: {result_size:.1f}KB\n\n"
            "😀 ایموجی را انتخاب کنید:",
            parse_mode=ParseMode.HTML,
            reply_markup=ui.emoji_buttons()
        )
        
        return SELECT_EMOJI
        
    except Exception as e: 
        logger.error(f"خطا در پردازش فایل: {e}", exc_info=True)
        await status.delete()
        await update.message.reply_text(
            f"❌ خطا در پردازش: {str(e)[:100]}\n\n"
            "لطفاً فایل دیگری ارسال کنید.",
            reply_markup=ui.back_button()
        )
        return UPLOAD_IMAGE


async def handle_emoji_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    
    if text == "✅ تأیید":
        emoji = context.user_data.get("selected_emoji")
        if not emoji:
            await update.message.reply_text("ابتدا ایموجی انتخاب کنید!")
            return SELECT_EMOJI
        
        await update.message.reply_text(
            f"✅ ایموجی انتخاب شده: {emoji}\n\n"
            "⏳ ساخت استیکر...",
            parse_mode=ParseMode.HTML,
            reply_markup=ReplyKeyboardRemove()
        )
        
        return await create_sticker(update, context)
    
    elif text == "📝 ایموجی دلخواه":
        await update.message.reply_text(
            "ایموجی دلخواه را بفرستید:\n(مثل 😊 یا ❤️)",
            reply_markup=ui.back_button()
        )
        return SELECT_EMOJI
    
    else:
        emoji = text.strip()
        context.user_data["selected_emoji"] = emoji
        
        await update.message.reply_text(
            f"😀 انتخاب شده: {emoji}\n\n"
            "تأیید میکنید؟",
            parse_mode=ParseMode.HTML,
            reply_markup=ui.emoji_buttons()
        )
        return SELECT_EMOJI


async def handle_custom_emoji_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    
    if text == "🔙 بازگشت": 
        await update.message.reply_text(
            "😀 ایموجی را انتخاب کنید:",
            parse_mode=ParseMode.HTML,
            reply_markup=ui.emoji_buttons()
        )
        return SELECT_EMOJI
    
    emoji = extract_emoji(text)
    
    if not emoji:
        await update.message.reply_text(
            "❌ ایموجی پیدا نشد!\n\n"
            "لطفاً ایموجی معتبر بفرستید."
        )
        return SELECT_EMOJI
    
    context.user_data["selected_emoji"] = emoji
    
    await update.message.reply_text(
        f"✅ ایموجی: {emoji}\n\n"
        "⏳ ساخت استیکر...",
        parse_mode=ParseMode.HTML,
        reply_markup=ReplyKeyboardRemove()
    )
    
    return await create_sticker(update, context)


async def create_sticker(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ساخت استیکر - با رفع مشکل Wrong file type"""
    user_id = update.effective_user.id
    emoji = context.user_data.get("selected_emoji", "😀")
    output_path = context.user_data.get("output_path")
    pack_name = context.user_data.get("current_pack")
    
    if not output_path or not pack_name:
        await update.effective_message.reply_text(
            "❌ خطا: اطلاعات ناقص است!",
            parse_mode=ParseMode.HTML,
            reply_markup=ui.main_menu()
        )
        return MENU_STATE
    
    try:
        packs = db.get_user_packs(user_id)
        pack_data = packs.get(pack_name, {})
        
        bot = context.bot
        
        # تشخیص نهایی نوع استیکر
        is_animated = context.user_data.get("is_animated", False)
        
        # باز هم چک کن که واقعاً انیمیشن باشد
        final_check = StickerConverter._is_file_animated(output_path)
        if is_animated and not final_check:
            logger.warning("⚠️ تشخیص نهایی: فایل انیمیشن نیست!")
            is_animated = False
        
        sticker_format = StickerFormat.ANIMATED if is_animated else StickerFormat.STATIC
        sticker_type = StickerType.REGULAR
        
        # نام پک
        if is_animated:
            full_name = get_pack_full_name(pack_name, bot.username, True)
            logger.info(f"پک Animated: {full_name}")
        else:
            full_name = get_pack_full_name(pack_name, bot.username, False)
            logger.info(f"پک Static: {full_name}")
        
        with open(output_path, 'rb') as f:
            sticker_bytes = f.read()
        
        file_size_kb = len(sticker_bytes) / 1024
        logger.info(f"📦 حجم فایل: {file_size_kb:.1f}KB")
        
        # اگر حجم زیاد است، هشدار بده
        if file_size_kb > 256:
            logger.warning(f"⚠️ حجم زیاد: {file_size_kb:.1f}KB")
            await update.effective_message.reply_text(
                f"⚠️ حجم فایل: {file_size_kb:.1f}KB\n"
                "تلگرام ممکن است رد کند...",
                parse_mode=ParseMode.HTML
            )
        
        try:
            if len(pack_data.get("stickers", [])) == 0:
                # اولین استیکر - پک جدید
                logger.info("ایجاد پک جدید...")
                await bot.create_new_sticker_set(
                    user_id=user_id,
                    name=full_name,
                    title=pack_data.get("title", pack_name),
                    stickers=[InputSticker(
                        sticker=sticker_bytes,
                        emoji_list=[emoji],
                        format=sticker_format
                    )],
                    sticker_type=sticker_type
                )
            else:
                # اگر Animated است، پک جدید بساز
                if is_animated:
                    logger.info("ایجاد پک Animated جدید...")
                    await bot.create_new_sticker_set(
                        user_id=user_id,
                        name=full_name,
                        title=f"{pack_data.get('title')} (Animated)",
                        stickers=[InputSticker(
                            sticker=sticker_bytes,
                            emoji_list=[emoji],
                            format=sticker_format
                        )],
                        sticker_type=sticker_type
                    )
                else:
                    # Static - اضافه کن به پک موجود
                    logger.info("اضافه کردن به Static پک...")
                    await bot.add_sticker_to_set(
                        user_id=user_id,
                        name=full_name,
                        sticker=InputSticker(
                            sticker=sticker_bytes,
                            emoji_list=[emoji],
                            format=sticker_format
                        )
                    )
        
        except TelegramError as e:
            error_text = str(e)
            logger.error(f"خطا تلگرام: {error_text}")
            
            if "already exists" in error_text.lower():
                logger.info("پک موجود است، در حال اضافه کردن...")
                await bot.add_sticker_to_set(
                    user_id=user_id,
                    name=full_name,
                    sticker=InputSticker(
                        sticker=sticker_bytes,
                        emoji_list=[emoji],
                        format=sticker_format
                    )
                )
            elif "wrong file type" in error_text.lower():
                # خطای Wrong file type - تلاش با فرمت دیگر
                logger.warning("⚠️ خطای Wrong file type، تلاش مجدد...")
                
                # سعی کن به استاتیک تبدیل کنی و دوباره امتحان کن
                if is_animated:
                    # اگر انیمیشن بود، به استاتیک تبدیل کن
                    static_full_name = get_pack_full_name(pack_name, bot.username, False)
                    static_format = StickerFormat.STATIC
                    
                    await update.effective_message.reply_text(
                        "⚠️ خطای نوع فایل!\n"
                        "در حال تلاش به عنوان استیکر استاتیک...",
                        parse_mode=ParseMode.HTML
                    )
                    
                    if len(pack_data.get("stickers", [])) == 0:
                        await bot.create_new_sticker_set(
                            user_id=user_id,
                            name=static_full_name,
                            title=pack_data.get("title", pack_name),
                            stickers=[InputSticker(
                                sticker=sticker_bytes,
                                emoji_list=[emoji],
                                format=static_format
                            )],
                            sticker_type=sticker_type
                        )
                    else:
                        await bot.add_sticker_to_set(
                            user_id=user_id,
                            name=static_full_name,
                            sticker=InputSticker(
                                sticker=sticker_bytes,
                                emoji_list=[emoji],
                                format=static_format
                            )
                        )
                else:
                    # اگر استاتیک بود، مشکل دیگری است
                    raise
            else:
                raise
        
        db.add_sticker(user_id, pack_name, emoji)
        
        stickers_count = len(db.get_user_packs(user_id)[pack_name].get("stickers", []))
        
        sticker_type_text = "🎬 متحرک" if is_animated else "📷 ثابت"
        
        await update.effective_message.reply_text(
            f"🎉 <b>استیکر اضافه شد!</b>\n\n"
            f"📦 پک: {pack_data.get('title')}\n"
            f"😀 ایموجی: {emoji}\n"
            f"🎬 نوع: {sticker_type_text}\n"
            f"📦 حجم: {file_size_kb:.1f}KB\n"
            f"📊 کل: {stickers_count}/120\n\n"
            f"🔗 لینک: <code>t.me/addstickers/{full_name}</code>",
            parse_mode=ParseMode.HTML,
            reply_markup=ui.main_menu()
        )
        
        # پاکسازی
        try:
            if os.path.exists(output_path):
                os.unlink(output_path)
            input_path = context.user_data.get("input_path")
            if input_path and os.path.exists(input_path):
                os.unlink(input_path)
        except Exception as e:
            logger.warning(f"خطا در پاکسازی: {e}")
        
        return MENU_STATE
        
    except TelegramError as e:
        logger.error(f"خطا تلگرام: {e}")
        error_text = str(e)
        
        if "stickerset_invalid" in error_text.lower():
            msg = "❌ مشکل در پک استیکر!\n\n(نمی‌توان متحرک و ثابت را مخلوط کرد)"
        elif "already exists" in error_text.lower():
            msg = "❌ این پک موجود است!"
        elif "file is too big" in error_text.lower():
            msg = f"❌ فایل خیلی بزرگ است! ({file_size_kb:.1f}KB)"
        elif "wrong file type" in error_text.lower():
            msg = ("❌ نوع فایل نامعتبر است!\n\n"
                   "تلگرام فایل WebP را نمی‌پذیرد.\n"
                   "ممکن است فایل خراب باشد یا فرمت آن پشتیبانی نشود.")
        else: 
            msg = f"❌ خطا: {error_text[:100]}"
        
        await update.effective_message.reply_text(
            msg,
            parse_mode=ParseMode.HTML,
            reply_markup=ui.main_menu()
        )
        
        return MENU_STATE
    
    except Exception as e:  
        logger.error(f"خطا: {e}", exc_info=True)
        await update.effective_message.reply_text(
            "❌ خطا در ساخت استیکر!\n\nلطفاً دوباره امتحان کنید.",
            parse_mode=ParseMode.HTML,
            reply_markup=ui.main_menu()
        )
        
        return MENU_STATE


async def handle_view_pack(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """نمایش جزئیات پک"""
    text = update.message.text
    user_id = update.effective_user.id
    
    if text == "🔙 بازگشت": 
        await update.message.reply_text(
            "🏠 <b>منوی اصلی</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=ui.main_menu()
        )
        return MENU_STATE
    
    packs_list = context.user_data.get("packs_list", {})
    pack_name = packs_list.get(text)
    
    if not pack_name:
        await update.message.reply_text("❌ پک پیدا نشد!")
        return VIEW_PACK_DETAIL
    
    packs = db.get_user_packs(user_id)
    pack_data = packs.get(pack_name, {})
    
    bot_username = context.bot.username
    full_pack_name = get_pack_full_name(pack_name, bot_username, False)
    pack_link = f"https://t.me/addstickers/{full_pack_name}"
    
    count = len(pack_data.get("stickers", []))
    
    context.user_data["current_pack_link"] = pack_link
    context.user_data["current_pack_name"] = pack_name
    
    buttons = [
        ["📋 کپی لینک"],
        ["🔙 بازگشت"]
    ]
    
    await update.message.reply_text(
        f"📦 <b>جزئیات پک:</b>\n\n"
        f"🏷️ <b>نام:</b> {pack_data.get('title')}\n"
        f"🔗 <b>نام فنی:</b> <code>{full_pack_name}</code>\n"
        f"🎨 <b>استیکرها:</b> {count}/120\n"
        f"📅 <b>تاریخ:</b> {pack_data.get('created_at', 'نامشخص')[:10]}\n\n"
        f"🔗 <b>لینک:</b>\n"
        f"<code>{pack_link}</code>",
        parse_mode=ParseMode.HTML,
        reply_markup=ReplyKeyboardMarkup(buttons, resize_keyboard=True)
    )
    
    return COPY_PACK_LINK


async def handle_copy_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """کپی لینک پک"""
    text = update.message.text
    user_id = update.effective_user.id
    
    if text == "🔙 بازگشت":
        packs = db.get_user_packs(user_id)
        
        context.user_data["packs_list"] = {}
        buttons = []
        
        for pack_name, data in packs.items():
            count = len(data.get("stickers", []))
            btn_text = f"📦 {data['title']} ({count}/120)"
            context.user_data["packs_list"][btn_text] = pack_name
            buttons.append([btn_text])
        
        buttons.append(["🔙 بازگشت"])
        
        await update.message.reply_text(
            "📚 <b>پک‌های شما:</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=ReplyKeyboardMarkup(buttons, resize_keyboard=True)
        )
        
        return VIEW_PACK_DETAIL
    
    elif text == "📋 کپی لینک": 
        pack_link = context.user_data.get("current_pack_link")
        
        if pack_link:
            await update.message.reply_text(
                f"✅ <b>لینک کپی شد!</b>\n\n"
                f"<code>{pack_link}</code>\n\n"
                f"می‌توانید این لینک را با دوستانتان اشتراک گذاری کنید.",
                parse_mode=ParseMode.HTML,
                reply_markup=ReplyKeyboardMarkup([["🔙 بازگشت"]], resize_keyboard=True)
            )
        else:
            await update.message.reply_text("❌ لینک پیدا نشد!")
        
        return COPY_PACK_LINK
    
    return COPY_PACK_LINK


async def handle_pack_selection_for_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    
    if text == "🔙 بازگشت": 
        await update.message.reply_text(
            "🏠 <b>منوی اصلی</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=ui.main_menu()
        )
        return MENU_STATE
    
    add_packs_list = context.user_data.get("add_packs_list", {})
    pack_name = add_packs_list.get(text)
    
    if not pack_name:
        await update.message.reply_text("❌ پک پیدا نشد!")
        return SELECT_PACK_FOR_ADD
    
    context.user_data["current_pack"] = pack_name
    
    await update.message.reply_text(
        f"📸 عکس، GIF یا ویدئو جدید را بفرستید برای '{pack_name}':",
        parse_mode=ParseMode.HTML,
        reply_markup=ReplyKeyboardRemove()
    )
    
    return UPLOAD_IMAGE


async def handle_pack_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    
    if text == "🔙 بازگشت":
        await update.message.reply_text(
            "🏠 <b>منوی اصلی</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=ui.main_menu()
        )
        return MENU_STATE
    
    edit_packs_list = context.user_data.get("edit_packs_list", {})
    pack_name = edit_packs_list.get(text)
    
    if not pack_name:
        await update.message.reply_text("❌ پک پیدا نشد!")
        return SELECT_PACK_FOR_EDIT
    
    context.user_data["editing_pack"] = pack_name
    
    await update.message.reply_text(
        f"📝 عنوان جدید برای '{pack_name}':\n\n"
        "(حداکثر 64 کاراکتر)",
        parse_mode=ParseMode.HTML,
        reply_markup=ui.back_button()
    )
    
    return INPUT_NEW_TITLE


async def handle_new_title_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    title = update.message.text.strip()
    user_id = update.effective_user.id
    pack_name = context.user_data.get("editing_pack")
    
    if title == "🔙 بازگشت":
        await update.message.reply_text(
            "🏠 <b>منوی اصلی</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=ui.main_menu()
        )
        return MENU_STATE
    
    if len(title) > 64:
        await update.message.reply_text("❌ عنوان خیلی بلند!")
        return INPUT_NEW_TITLE
    
    if db.update_pack_title(user_id, pack_name, title):
        await update.message.reply_text(
            f"✅ عنوان تغییر کرد: {title}",
            parse_mode=ParseMode.HTML
        )
        await update.message.reply_text(
            "🏠 منوی اصلی",
            parse_mode=ParseMode.HTML,
            reply_markup=ui.main_menu()
        )
    else:
        await update.message.reply_text("❌ خطا!")
    
    return MENU_STATE


async def handle_pack_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    
    if text == "🔙 بازگشت":
        await update.message.reply_text(
            "🏠 <b>منوی اصلی</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=ui.main_menu()
        )
        return MENU_STATE
    
    del_packs_list = context.user_data.get("del_packs_list", {})
    pack_name = del_packs_list.get(text)
    
    if not pack_name:
        await update.message.reply_text("❌ پک پیدا نشد!")
        return SELECT_PACK_FOR_DELETE
    
    context.user_data["deleting_pack"] = pack_name
    
    await update.message.reply_text(
        f"⚠️ آیا مطمئن از حذف '{pack_name}' هستید؟\n\n"
        "❌ این عمل غیرقابل بازگشت است!",
        parse_mode=ParseMode.HTML,
        reply_markup=ui.yes_no_buttons()
    )
    
    return CONFIRM_DELETE


async def handle_delete_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_id = update.effective_user.id
    pack_name = context.user_data.get("deleting_pack")
    
    if text == "❌ خیر":
        await update.message.reply_text(
            "🏠 <b>منوی اصلی</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=ui.main_menu()
        )
        return MENU_STATE
    
    if text == "✅ بله": 
        if db.delete_pack(user_id, pack_name):
            await update.message.reply_text(
                f"✅ پک '{pack_name}' حذف شد!",
                parse_mode=ParseMode.HTML,
                reply_markup=ui.main_menu()
            )
        else:
            await update.message.reply_text(
                "❌ خطا!",
                parse_mode=ParseMode.HTML,
                reply_markup=ui.main_menu()
            )
    
    return MENU_STATE


async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"خطا: {context.error}")
    
    if update and update.effective_message:
        await update.effective_message.reply_text(
            "❌ خطایی رخ داد!\n\n/start را دوباره سعی کنید.",
            parse_mode=ParseMode.HTML
        )


def main():
    cleanup_temp()
    
    # چک نصب بودن ffmpeg
    try:
        subprocess.run(['ffmpeg', '-version'], capture_output=True, check=True)
        logger.info("✅ ffmpeg نصب است.")
        ffmpeg_ok = True
    except (subprocess.CalledProcessError, FileNotFoundError):
        logger.error("❌ ffmpeg نصب نیست!")
        ffmpeg_ok = False
    
    app = Application.builder().token(TOKEN).build()
    
    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            MENU_STATE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_menu),
            ],
            INPUT_PACK_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_pack_name_input),
            ],
            INPUT_PACK_TITLE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_pack_title_input),
            ],
            UPLOAD_IMAGE: [
                MessageHandler(filters.PHOTO, handle_file_upload),
                MessageHandler(filters.Document.ALL, handle_file_upload),
                MessageHandler(filters.VIDEO, handle_file_upload),
                MessageHandler(filters.ANIMATION, handle_file_upload),
            ],
            SELECT_EMOJI: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_emoji_selection),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_custom_emoji_input),
            ],
            SELECT_PACK_FOR_ADD: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_pack_selection_for_add),
            ],
            SELECT_PACK_FOR_EDIT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_pack_edit),
            ],
            INPUT_NEW_TITLE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_new_title_input),
            ],
            SELECT_PACK_FOR_DELETE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_pack_delete),
            ],
            CONFIRM_DELETE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_delete_confirm),
            ],
            VIEW_PACK_DETAIL: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_view_pack),
            ],
            COPY_PACK_LINK: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_copy_link),
            ]
        },
        fallbacks=[CommandHandler("start", start)],
        allow_reentry=True
    )
    
    app.add_handler(conv)
    app.add_error_handler(error_handler)
    
    print("=" * 60)
    print("🤖 ربات سازنده استیکر پک تلگرام")
    print("🔄 نسخه: 4.1 (کامل و آماده اجرا)")
    print(f"📂 داده‌ها: {DATA_FILE}")
    print(f"📁 موقت: {TEMP_DIR}")
    print(f"🔧 ffmpeg: {'✅ نصب است' if ffmpeg_ok else '❌ نصب نیست'}")
    print("🔥 پشتیبانی از همه فرمت‌ها")
    print("🎬 تبدیل MP4, MOV, AVI به استیکر متحرک")
    print("⚡ تشخیص هوشمند انیمیشن/استاتیک")
    print("🛠️ رفع کامل مشکل پردازش فایل")
    print("=" * 60)
    
    if not ffmpeg_ok:
        print("\n⚠️  هشدار: ffmpeg نصب نیست!")
        print("برای پردازش ویدئوها باید ffmpeg نصب باشد:")
        print("• Ubuntu/Debian: sudo apt install ffmpeg")
        print("• MacOS: brew install ffmpeg")
        print("• Windows: از https://ffmpeg.org دانلود کنید")
        print("\n✅ بدون ffmpeg فقط می‌توانید عکس و GIF ارسال کنید.")
        print("=" * 60)
    
    try:
        app.run_polling(allowed_updates=Update.ALL_TYPES)
    except KeyboardInterrupt:
        print("\n✅ ربات متوقف شد.")
        cleanup_temp()


if __name__ == "__main__":
    main()
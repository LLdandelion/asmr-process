'''
用来处理asmr的python，环境conda-py3.8
功能1（ROOT_DIR）：wav转flac，vtt文件转lrc，正则表达式捕获命名
功能2（JP_DIR）：翻译文件及其文件夹
功能3（ROOT_DIR）：获取文件夹内图片用于专辑封面，获取文件名用于标题，获取父文件夹名用于专辑
根目录、翻译目录、腾讯云api自己在变量定义中设置
没有ffmpeg自己找教程安装，或者自己把第一部分的wav转flac注释掉，这会导致不处理wav文件，解决方法就是自己在第三部分的处理中写一个处理wav文件的if语句
'''


import os
import sys
import subprocess
import mutagen
import re
import shutil
import logging
import time
from pathlib import Path
from mutagen.flac import FLAC
from mutagen.id3 import ID3, APIC, TIT2, TALB
from mutagen.mp3 import MP3
from mutagen.mp4 import MP4, MP4Cover
from tencentcloud.common import credential
from tencentcloud.common.exception.tencent_cloud_sdk_exception import TencentCloudSDKException
from tencentcloud.tmt.v20180321 import tmt_client, models
from tencentcloud.common.profile.http_profile import HttpProfile
from tencentcloud.common.profile.client_profile import ClientProfile

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# 常量定义

ROOT_DIR = r"" #根目录
JP_DIR = r'' #根目录下自己弄一个专门用来翻译的文件夹
SECRET_ID = '' #腾讯云api
SECRET_KEY = ''
ILLEGAL_CHARS = r'[\\/:*?"<>|]'
AUDIO_EXTS = {'.wav', '.mp3', '.flac', '.m4a'}
SUBTITLE_EXTS = {'.wav.vtt', '.mp3.vtt', '.flac.vtt', '.m4a.vtt', '.vtt', '.lrc'}
IMAGE_EXTS = {'.jpg', '.jpeg', '.png'}

# 特定字符正则表达式

PATTERNS = re.compile(r'''
^
(?:【|「|)? #主体部分 
(?:track|tr|ＴＲ|RJ\d{1,8})?
(?:EX|SP)?
[ ]?
[-]?
[ ]?
(\d{1,2})?
[_# ]?
(?:トラック)?
(?:\d{1,2}|EX|SP)
(?:-A|-B)?
[_. ]?
(?:】|]|」|)?
(?:」)?
(?:tr|track)? #补充1
(?:sp|ex|\d{1,2})?
[_ ]?
(?:n|hi|el|h|mr)? #补充2
(?:\d{1,2}| \d{1,2} )?
(?:r)?
[_-]?
(?:tr\d{1,2}|\d{1,2})?
[_]?
(?:【Trck\d{1,2}】)? #补充3
''',re.IGNORECASE|re.VERBOSE)

# ======================== 预处理模块 ========================
def classify_files(folder_path):
    """
    分类文件夹中的文件（音频、字幕、图片）

    参数:
        folder_path: 文件夹路径

    返回:
        (audio_files, subtitle_files, image_files)
    """
    audio_files = []
    subtitle_files = []
    image_files = []

    for filename in os.listdir(folder_path):
        file_path = os.path.join(folder_path, filename)
        if not os.path.isfile(file_path):
            continue

        filename_lower = filename.lower()

        if any(filename_lower.endswith(ext) for ext in AUDIO_EXTS):
            audio_files.append(file_path)
        elif any(ext in filename_lower for ext in SUBTITLE_EXTS):
            subtitle_files.append(file_path)
        elif any(filename_lower.endswith(ext) for ext in IMAGE_EXTS):
            image_files.append(file_path)

    return audio_files, subtitle_files, image_files


def convert_wav_to_flac(wav_path):
    """
    使用ffmpeg将WAV转换为FLAC

    参数:
        wav_path: WAV文件路径

    返回:
        成功: 新FLAC文件路径
        失败: None
    """
    wav_path_obj = Path(wav_path)
    flac_path = wav_path_obj.with_suffix('.flac')

    try:
        cmd = ['ffmpeg', '-i', str(wav_path_obj), '-compression_level', '12', '-y', str(flac_path)]
        process = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=subprocess.CREATE_NO_WINDOW
        )

        if process.returncode != 0:
            logger.error(f"转换失败: {wav_path_obj.name} - 错误代码 {process.returncode}")
            return None

        if not flac_path.exists():
            logger.error(f"转换失败: {wav_path_obj.name} - 未生成输出文件")
            return None

        try:
            os.remove(wav_path)
            logger.info(f"转换成功并删除原文件: {wav_path_obj.name} -> {flac_path.name}")
            return str(flac_path)
        except Exception as e:
            logger.error(f"无法删除原文件 {wav_path_obj.name}: {str(e)}")
            return None

    except Exception as e:
        logger.error(f"转换失败: {wav_path_obj.name} - {str(e)}")
        return None


def normalize_subtitle_filename(subtitle_path):
    """
    标准化字幕文件名（去除冗余扩展名）

    参数:
        subtitle_path: 字幕文件路径

    返回:
        成功: 新路径
        失败: None
    """
    path_obj = Path(subtitle_path)
    filename_lower = path_obj.name.lower()

    if filename_lower.endswith('.wav.vtt'):
        new_path = path_obj.with_name(path_obj.stem.replace('.wav', '') + '.vtt')
    elif filename_lower.endswith('.mp3.vtt'):
        new_path = path_obj.with_name(path_obj.stem.replace('.mp3', '') + '.vtt')
    elif filename_lower.endswith('.flac.vtt'):
        new_path = path_obj.with_name(path_obj.stem.replace('.flac', '') + '.vtt')
    elif filename_lower.endswith('.m4a.vtt'):
        new_path = path_obj.with_name(path_obj.stem.replace('.m4a', '') + '.vtt')
    elif filename_lower.endswith('.vtt'):
        new_path = path_obj
    else:
        return None

    try:
        if str(new_path) != subtitle_path:
            shutil.move(subtitle_path, new_path)
            logger.info(f"字幕重命名: {path_obj.name} -> {new_path.name}")
        return new_path
    except Exception as e:
        logger.error(f"字幕重命名失败: {path_obj.name} - {str(e)}")
        return None


def convert_vtt_to_lrc(vtt_path):
    """
    将VTT字幕转换为LRC格式并删除原文件

    参数:
        vtt_path: VTT文件路径
    """
    path_obj = Path(vtt_path)
    lrc_path = path_obj.with_suffix('.lrc')

    try:
        # 尝试不同编码打开文件
        encodings = ['utf-8', 'gbk', 'latin-1', 'cp1252']
        content = None
        for encoding in encodings:
            try:
                with open(vtt_path, 'r', encoding=encoding) as f:
                    content = f.readlines()
                break
            except UnicodeDecodeError:
                continue

        if content is None:
            logger.error(f"字幕转换失败: 无法解码文件 - {path_obj.name}")
            return

        # 转换内容格式
        lrc_content = []
        for line in content:
            line = line.strip()
            if not line or 'WEBVTT' in line or 'NOTE' in line or line.isdigit():
                continue

            if '-->' in line:
                parts = line.split('-->')
                start_time = parts[0].strip()

                # 处理时间格式
                if start_time.count(':') == 2:
                    h, m, sm = start_time.split(':')
                    s, ms = sm.split('.') if '.' in sm else (sm, '000')
                    seconds = f"{int(m) + int(h) * 60:02d}:{s}.{ms[:2]}"
                else:
                    seconds = start_time.replace('.', ',', 1)

                lrc_content.append(f"[{seconds}]")
            else:
                lrc_content.append(line)

        # 写入新文件
        with open(lrc_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lrc_content))

        os.remove(vtt_path)
        logger.info(f"字幕转换: {path_obj.name} -> {lrc_path.name}")

    except Exception as e:
        logger.error(f"字幕转换失败: {path_obj.name} - {str(e)}")


def associate_audio_subtitles(audio_files, subtitle_files):
    """
    将字幕文件与同名音频文件相关联

    参数:
        audio_files: 音频文件列表
        subtitle_files: 字幕文件列表

    返回:
        字典: {音频路径: [关联字幕路径1, ...]}
    """
    associations = {}
    base_name_map = {}

    # 创建音频基础名映射
    for audio_path in audio_files:
        base_name = Path(audio_path).stem
        base_name_map[base_name] = audio_path

    # 关联字幕文件
    for sub_path in subtitle_files:
        sub_base = Path(sub_path).stem
        if sub_base in base_name_map:
            audio_path = base_name_map[sub_base]
            if audio_path not in associations:
                associations[audio_path] = []
            associations[audio_path].append(sub_path)

    return associations


def remove_patterns(filename):
    """
    移除文件名中的特定模式字符

    参数:
        filename: 原始文件名（不含扩展名）

    返回:
        清理后的文件名
    """
    cleaned = filename
    cleaned = re.sub(PATTERNS, '', cleaned)
    return cleaned.strip()


def rename_file_with_counter(file_path, counter):
    """
    使用编号重命名文件

    参数:
        file_path: 文件路径
        counter: 当前计数器值

    返回:
        新文件路径
    """
    path_obj = Path(file_path)
    cleaned_name = remove_patterns(path_obj.stem)
    new_name = f"「{counter:02d}」{cleaned_name}{path_obj.suffix}"
    new_path = path_obj.with_name(new_name)

    try:
        path_obj.rename(new_path)
        file_type = "音频" if path_obj.suffix.lower() in AUDIO_EXTS else "字幕"
        logger.info(f"编号重命名({file_type}): {path_obj.name} -> {new_name}")
        return str(new_path)
    except Exception as e:
        logger.error(f"编号重命名失败: {path_obj.name} - {str(e)}")
        return None


def process_folder(folder_path):
    """
    处理单个文件夹（预处理流程）

    参数:
        folder_path: 文件夹路径
    """
    logger.info(f"处理文件夹: {folder_path}")
    audio_files, subtitle_files, _ = classify_files(folder_path)

    # 1. 处理字幕文件
    for sub_path in subtitle_files[:]:
        normalized = normalize_subtitle_filename(sub_path)
        if normalized:
            # 更新路径（如果重命名）
            subtitle_files.remove(sub_path)
            subtitle_files.append(str(normalized))

            # 转换VTT为LRC
            if str(normalized).endswith('.vtt'):
                convert_vtt_to_lrc(str(normalized))
                new_path = normalized.with_suffix('.lrc')
                subtitle_files.remove(str(normalized))
                subtitle_files.append(str(new_path))

    # 2. 处理音频文件
    counter = 1
    audio_files.sort(key=lambda x: Path(x).name.lower())

    for audio_path in audio_files[:]:
        # 转换WAV为FLAC
        if Path(audio_path).suffix.lower() == '.wav':
            new_path = convert_wav_to_flac(audio_path)
            if new_path:
                audio_files.remove(audio_path)
                audio_files.append(new_path)
                audio_path = new_path

    # 3. 关联音频和字幕
    associations = associate_audio_subtitles(audio_files, subtitle_files)

    # 4. 重命名音频和关联字幕
    for audio_path in audio_files:
        # 重命名音频文件
        new_audio_path = rename_file_with_counter(audio_path, counter)
        if not new_audio_path:
            continue

        # 更新关联
        if audio_path in associations:
            for sub_path in associations[audio_path]:
                if os.path.exists(sub_path):
                    # 重命名关联字幕
                    rename_file_with_counter(sub_path, counter)
                    # 从待处理列表中移除
                    if sub_path in subtitle_files:
                        subtitle_files.remove(sub_path)

        counter += 1

    # 5. 重命名剩余字幕
    for sub_path in subtitle_files:
        if os.path.exists(sub_path):
            rename_file_with_counter(sub_path, counter)
            counter += 1


def preprocess_directory(root_dir):
    """
    预处理目录（遍历所有子文件夹）

    参数:
        root_dir: 根目录路径
    """
    for foldername, subfolders, filenames in os.walk(root_dir):
        process_folder(foldername)


# ======================== 翻译模块 ========================
class Translator:
    """腾讯云翻译服务封装"""

    def __init__(self, secret_id, secret_key):
        """初始化翻译客户端"""
        self.cred = credential.Credential(secret_id, secret_key)
        http_profile = HttpProfile()
        http_profile.endpoint = "tmt.tencentcloudapi.com"
        client_profile = ClientProfile()
        client_profile.httpProfile = http_profile
        self.client = tmt_client.TmtClient(self.cred, "ap-guangzhou", client_profile)

    def translate_text(self, text):
        """翻译文本到中文"""
        try:
            req = models.TextTranslateRequest()
            req.SourceText = text
            req.Source = "ja"
            req.Target = "zh"
            req.ProjectId = 0

            resp = self.client.TextTranslate(req)
            return resp.TargetText
        except TencentCloudSDKException as e:
            logger.error(f"翻译错误: {e}")
            return None
        except Exception as e:
            logger.error(f"未知翻译错误: {e}")
            return None


def sanitize_name(name):
    """
    清理名称中的非法字符

    参数:
        name: 原始名称

    返回:
        清理后的名称
    """
    return re.sub(ILLEGAL_CHARS, '。', name)


def translate_and_rename_file(file_path, translator):
    """
    翻译并重命名单个文件

    参数:
        file_path: 文件路径
        translator: 翻译器实例

    返回:
        是否成功
    """
    path_obj = Path(file_path)
    stem = path_obj.stem

    # 解析文件名中的编号和原始名称
    match = re.match(r'(?:「(\d{2})」|【(\d{2})】)(.*)', stem)
    if match:
        number = match.group(1) or match.group(2)
        original_name = match.group(3).strip()
    else:
        number = None
        original_name = stem

    # 翻译名称
    translated = translator.translate_text(original_name)
    if not translated:
        logger.warning(f"翻译失败: {original_name}")
        return False

    # 清理非法字符
    translated = sanitize_name(translated)

    # 构建新文件名
    if number:
        new_name = f"「{number}」{translated}[{original_name}]{path_obj.suffix}"
    else:
        new_name = f"{translated}[{original_name}]{path_obj.suffix}"

    new_path = path_obj.with_name(new_name)

    try:
        path_obj.rename(new_path)
        logger.info(f"文件翻译重命名: {path_obj.name} -> {new_name}")
        time.sleep(0.2)  # API速率限制
        return True
    except Exception as e:
        logger.error(f"文件重命名失败: {path_obj.name} -> {new_name}, 错误: {e}")
        return False


def translate_and_rename_directory(dir_path, translator):
    """
    翻译并重命名目录

    参数:
        dir_path: 目录路径
        translator: 翻译器实例

    返回:
        是否成功
    """
    path_obj = Path(dir_path)
    original_name = path_obj.name

    # 翻译目录名
    translated = translator.translate_text(original_name)
    if not translated:
        logger.warning(f"目录翻译失败: {original_name}")
        return False

    # 清理非法字符
    translated = sanitize_name(translated)

    # 构建新目录名
    new_name = f"{translated}[{original_name}]"
    new_path = path_obj.parent / new_name

    try:
        path_obj.rename(new_path)
        logger.info(f"目录翻译重命名: {original_name} -> {new_name}")
        time.sleep(0.2)  # API速率限制
        return True
    except Exception as e:
        logger.error(f"目录重命名失败: {original_name} -> {new_name}, 错误: {e}")
        return False


def get_deepest_directories(root_dir):
    """
    获取按深度排序的目录树（深度优先）

    参数:
        root_dir: 根目录路径

    返回:
        目录路径列表（按深度从深到浅排序）
    """
    dirs_by_depth = {}

    for dirpath, dirnames, filenames in os.walk(root_dir):
        depth = len(Path(dirpath).relative_to(root_dir).parts)

        if depth not in dirs_by_depth:
            dirs_by_depth[depth] = []
        dirs_by_depth[depth].append(dirpath)

    # 按深度排序（从深到浅）
    sorted_dirs = []
    for depth in sorted(dirs_by_depth.keys(), reverse=True):
        sorted_dirs.extend(dirs_by_depth[depth])

    return sorted_dirs


def process_files_for_translation(dir_path, translator):
    """
    处理目录中的文件（翻译流程）

    参数:
        dir_path: 目录路径
        translator: 翻译器实例
    """
    # 获取目录中的文件
    audio_files = []
    subtitle_files = []

    for filename in os.listdir(dir_path):
        file_path = os.path.join(dir_path, filename)
        if not os.path.isfile(file_path):
            continue

        ext = Path(filename).suffix.lower()
        if ext in AUDIO_EXTS:
            audio_files.append(file_path)
        elif ext == '.lrc':
            subtitle_files.append(file_path)

    # 关联音频和字幕
    associations = associate_audio_subtitles(audio_files, subtitle_files)

    # 处理音频文件
    for audio_path in audio_files:
        # 翻译并重命名音频
        if translate_and_rename_file(audio_path, translator):
            # 处理关联的字幕
            if audio_path in associations:
                for sub_path in associations[audio_path]:
                    if os.path.exists(sub_path):
                        translate_and_rename_file(sub_path, translator)


def translate_jp_directory(jp_dir, secret_id, secret_key):
    """
    翻译日语目录（文件优先，目录后处理）

    参数:
        jp_dir: 日语目录路径
        secret_id: 腾讯云Secret ID
        secret_key: 腾讯云Secret Key
    """
    translator = Translator(secret_id, secret_key)

    # 第一步：处理文件（深度优先）
    dirs_to_process = get_deepest_directories(jp_dir)
    for dir_path in dirs_to_process:
        logger.info(f"处理文件: {dir_path}")
        process_files_for_translation(dir_path, translator)

    # 第二步：处理目录（深度优先）
    dirs_to_process = get_deepest_directories(jp_dir)
    for dir_path in dirs_to_process:
        if dir_path != JP_DIR:
            logger.info(f"处理目录: {dir_path}")
            translate_and_rename_directory(dir_path, translator)


# ======================== 标签更新模块 ========================
def find_cover_image(audio_path, image_files):
    """
    为音频文件查找匹配的封面图片

    参数:
        audio_path: 音频文件路径
        image_files: 图片文件列表

    返回:
        封面图片路径或None
    """
    audio_stem = Path(audio_path).stem

    # 1. 优先查找同名图片
    for img in image_files:
        if Path(img).stem == audio_stem:
            return img

    # 2. 查找文件夹中的通用封面
    common_names = ['cover', 'folder', 'front', 'album']
    for name in common_names:
        for img in image_files:
            if Path(img).stem.lower() == name:
                return img

    # 3. 返回文件夹中第一张图片
    return image_files[0] if image_files else None


def tag_audio_file(audio_path, cover_image=None):
    """
    为音频文件添加元数据标签

    参数:
        audio_path: 音频文件路径
        cover_image: 封面图片路径

    返回:
        是否成功
    """
    try:
        # 获取标签数据
        folder = Path(audio_path).parent.name
        title = Path(audio_path).stem

        audio_path_obj = Path(audio_path)
        ext = audio_path_obj.suffix.lower()

        # 添加封面图片
        cover_data = None
        if cover_image and os.path.exists(cover_image):
            with open(cover_image, 'rb') as f:
                cover_data = f.read()

        # MP3文件处理
        if ext == '.mp3':
            audio = MP3(audio_path, ID3=ID3)
            if not audio.tags:
                audio.add_tags()

            audio.tags.add(TIT2(encoding=3, text=title))
            audio.tags.add(TALB(encoding=3, text=folder))

            if cover_data:
                img_ext = Path(cover_image).suffix.lower()
                mime_type = 'image/jpeg' if img_ext in ['.jpg', '.jpeg'] else f'image/{img_ext[1:]}'

                audio.tags.add(APIC(
                    encoding=3,
                    mime=mime_type,
                    type=3,
                    desc='Cover',
                    data=cover_data
                ))
            audio.save()

        # FLAC文件处理
        elif ext == '.flac':
            audio = FLAC(audio_path)
            audio.delete()
            audio['title'] = title
            audio['album'] = folder

            if cover_data:
                image = mutagen.flac.Picture()
                image.type = 3
                img_ext = Path(cover_image).suffix.lower()
                image.mime = 'image/jpeg' if img_ext in ['.jpg', '.jpeg'] else f'image/{img_ext[1:]}'
                image.data = cover_data
                audio.add_picture(image)
            audio.save()

        # M4A文件处理
        elif ext == '.m4a':
            audio = MP4(audio_path)

            # 保留原有封面
            existing_covers = audio.get('covr', [])

            # 仅当没有封面且提供了新封面时添加
            if not existing_covers and cover_image and os.path.exists(cover_image):
                with open(cover_image, 'rb') as f:
                    cover_data = f.read()

                img_ext = Path(cover_image).suffix.lower()
                cover_format = MP4Cover.FORMAT_PNG if img_ext == '.png' else MP4Cover.FORMAT_JPEG
                existing_covers.append(MP4Cover(cover_data, imageformat=cover_format))

            # 更新标签但保留其他元数据
            audio['©nam'] = [title]
            audio['©alb'] = [folder]

            if existing_covers:
                audio['covr'] = existing_covers

            audio.save()

        return True
    except Exception as e:
        logger.error(f"标签处理出错: {Path(audio_path).name} - {str(e)}")
        return False


def update_tags_for_folder(folder_path):
    """
    更新单个文件夹的音频标签

    参数:
        folder_path: 文件夹路径
    """
    logger.info(f"更新标签: {folder_path}")
    audio_files, _, image_files = classify_files(folder_path)

    for audio_path in audio_files:
        cover_image = find_cover_image(audio_path, image_files)
        if cover_image:
            logger.info(f"  使用封面: {Path(cover_image).name}")

        success = tag_audio_file(audio_path, cover_image)
        status = "成功" if success else "失败"
        logger.info(f"  标签更新: {Path(audio_path).name} - {status}")


def update_all_tags(root_dir):
    """
    更新目录中所有音频文件的标签

    参数:
        root_dir: 根目录路径
    """
    for foldername, subfolders, filenames in os.walk(root_dir):
        update_tags_for_folder(foldername)


# ======================== 主流程控制 ========================
def check_ffmpeg_available():
    """检查ffmpeg是否可用"""
    try:
        subprocess.run(
            ['ffmpeg', '-version'],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
            creationflags=subprocess.CREATE_NO_WINDOW
        )
        return True
    except Exception:
        logger.error("系统PATH中未找到ffmpeg，请先安装并添加到环境变量")
        return False


def main_workflow():
    """主工作流程控制"""
    # 1. 检查目录有效性
    if not os.path.isdir(ROOT_DIR):
        logger.error(f"根目录不存在: {ROOT_DIR}")
        return
    if not os.path.isdir(JP_DIR):
        logger.error(f"日语目录不存在: {JP_DIR}")
        return

    # 2. 预处理（转换音频和字幕）
    logger.info("\n=== 开始预处理 ===")
    preprocess_directory(ROOT_DIR)

    # 3. 翻译（日语目录）
    logger.info("\n=== 开始翻译 ===")
    translate_jp_directory(JP_DIR, SECRET_ID, SECRET_KEY)

    # 4. 更新标签
    logger.info("\n=== 开始更新标签 ===")
    update_all_tags(ROOT_DIR)

    logger.info("\n=== 所有处理完成 ===")


def main():
    """主函数入口"""
    if not check_ffmpeg_available():
        return

    main_workflow()


if __name__ == '__main__':
    main()
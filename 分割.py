"""
小说分割程序
功能：将大型TXT小说文件按章节分割，每10章保存为一个文件
"""

import os
import re
from pathlib import Path

# 每个文件包含的章节数
CHAPTERS_PER_FILE = 20
class NovelSplitter:
    """小说分割器类"""

    def __init__(self, input_file: str, output_dir: str = "TXT", chapters_per_file: int = 10):
        """
        初始化分割器

        Args:
            input_file: 输入的小说文件路径
            output_dir: 输出文件夹名称（默认TXT）
            chapters_per_file: 每个文件包含的章节数（默认10章）
        """
        self.input_file = input_file
        self.output_dir = output_dir
        self.chapters_per_file = chapters_per_file

        # 中文数字到阿拉伯数字的映射
        self.chinese_nums = {
            '零': 0, '一': 1, '二': 2, '三': 3, '四': 4,
            '五': 5, '六': 6, '七': 7, '八': 8, '九': 9,
            '十': 10, '百': 100, '千': 1000, '万': 10000
        }

    def chinese_to_num(self, chinese: str) -> int:
        """
        将中文数字转换为阿拉伯数字
        支持格式：一百二十三、一千零五、十、二十一等

        Args:
            chinese: 中文数字字符串

        Returns:
            对应的阿拉伯数字
        """
        if not chinese:
            return 0

        # 处理纯阿拉伯数字的情况
        if chinese.isdigit():
            return int(chinese)

        result = 0
        temp = 0

        for char in chinese:
            if char in self.chinese_nums:
                num = self.chinese_nums[char]
                if num >= 10:  # 十、百、千、万
                    if temp == 0:
                        temp = 1
                    result += temp * num
                    temp = 0
                else:
                    temp = temp * 10 + num if temp > 0 else num

        result += temp
        return result

    def extract_chapter_number(self, title: str) -> int:
        """
        从章节标题中提取章节号

        Args:
            title: 章节标题，如"第一章"、"第123章"、"第一百章"等

        Returns:
            章节号（阿拉伯数字），如果无法提取则返回0
        """
        # 匹配"第X章"格式，X可以是中文数字或阿拉伯数字
        # 支持如：第1章．神奇的任务 / 第十二章 / 第12章
        match = re.search(r'第([一二三四五六七八九十百千万零\d]+)章', title)
        if match:
            num_str = match.group(1)
            return self.chinese_to_num(num_str)

        return 0

    def split_chapters(self, content: str) -> list:
        """
        将文本内容按章节分割

        Args:
            content: 小说全文内容

        Returns:
            章节列表，每个元素为(章节标题, 章节内容)的元组
        """
        chapters = []

        # 章节标题匹配模式（支持如：第1章．神奇的任务）
        # 注意：这里不能使用 \s（会匹配换行），否则会把下一行正文误并入章节标题
        chapter_pattern = r'(^[ \t\u3000]*第[一二三四五六七八九十百千万零\d]+章(?:[．。.:：、 \t\u3000—-]*[^\n]*)?$)'

        # 分割文本
        parts = re.split(chapter_pattern, content, flags=re.MULTILINE)

        current_title = None
        seen_chapter_numbers = set()
        current_content = []

        for part in parts:
            if not part.strip():
                continue

            # 检查是否是章节标题
            if re.match(chapter_pattern, part.strip(), flags=re.MULTILINE):
                new_title = part.strip()
                chapter_num = self.extract_chapter_number(new_title)

                # 重复章节号仅保留第一次出现，后续同章节号标题行直接跳过
                if chapter_num > 0 and chapter_num in seen_chapter_numbers:
                    continue

                # 保存上一章节
                if current_title and current_content:
                    chapters.append((current_title, '\n'.join(current_content)))

                current_title = new_title
                if chapter_num > 0:
                    seen_chapter_numbers.add(chapter_num)
                current_content = []
            else:
                # 章节内容
                clean_part = part.strip('\r\n')
                if current_title and clean_part.strip():
                    current_content.append(clean_part)

        # 保存最后一章
        if current_title and current_content:
            chapters.append((current_title, '\n'.join(current_content)))

        return chapters

    def process(self) -> None:
        """
        执行分割处理
        """
        try:
            # 检查输入文件是否存在
            if not os.path.exists(self.input_file):
                raise FileNotFoundError(f"输入文件不存在: {self.input_file}")

            print(f"正在读取文件: {self.input_file}")

            # 读取文件内容（使用UTF-8编码）
            with open(self.input_file, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()

            print(f"文件读取完成，共 {len(content)} 字符")

            # 分割章节
            print("正在分析章节结构...")
            chapters = self.split_chapters(content)

            if not chapters:
                print('未检测到章节标题，请检查文件格式是否为"第X章．标题"格式')
                return

            print(f"共检测到 {len(chapters)} 个章节")

            # 创建输出目录
            output_path = Path(self.output_dir)
            output_path.mkdir(exist_ok=True)
            print(f"输出目录: {output_path.absolute()}")

            # 按每N章分组保存
            total_groups = (len(chapters) + self.chapters_per_file - 1) // self.chapters_per_file

            for group_idx in range(total_groups):
                start_idx = group_idx * self.chapters_per_file
                end_idx = min(start_idx + self.chapters_per_file, len(chapters))

                # 获取该组的章节
                group_chapters = chapters[start_idx:end_idx]

                # 获取起始和结束章节号
                start_chapter = self.extract_chapter_number(group_chapters[0][0])
                end_chapter = self.extract_chapter_number(group_chapters[-1][0])

                # 如果无法提取章节号，使用索引代替
                if start_chapter == 0:
                    start_chapter = start_idx + 1
                if end_chapter == 0:
                    end_chapter = end_idx

                # 生成文件名
                filename = f"{start_chapter:05d}-{end_chapter:05d}.txt"
                filepath = output_path / filename
                chapter_range = f"第{start_chapter:05d}-{end_chapter:05d}章"

                # 写入文件：过滤空行，不输出空行
                output_lines = [chapter_range]
                for _, chapter_content in group_chapters:
                    output_lines.extend(
                        line for line in chapter_content.splitlines() if line.strip()
                    )

                with open(filepath, 'w', encoding='utf-8') as f:
                    f.write('\n'.join(output_lines))

                print(f"已保存: {filename} (包含第{start_chapter}章到第{end_chapter}章)")

            print(f"分割完成！共生成 {total_groups} 个文件，保存在 {output_path.absolute()} 目录下")

        except FileNotFoundError as e:
            print(f"错误: {e}")
        except PermissionError:
            print(f"错误: 没有权限访问文件或目录")
        except UnicodeDecodeError as e:
            print(f"错误: 文件编码错误，请确保文件使用UTF-8编码 - {e}")
        except Exception as e:
            print(f"处理过程中发生错误: {e}")


def main():
    """
    主函数 - 可配置参数
    """
    # ==================== 配置区域 ====================
    # 输入文件名（请修改为实际的小说文件名）
    INPUT_FILE = "校花的贴身高手.txt"

    # 输出文件夹名称（默认TXT）
    OUTPUT_DIR = "TXT"

    # =================================================

    # 创建分割器实例并执行
    splitter = NovelSplitter(
        input_file=INPUT_FILE,
        output_dir=OUTPUT_DIR,
        chapters_per_file=CHAPTERS_PER_FILE
    )

    splitter.process()


if __name__ == "__main__":
    main()

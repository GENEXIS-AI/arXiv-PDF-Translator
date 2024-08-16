import subprocess
import os
import re
import tarfile
import requests
import concurrent.futures
import openai  # GPT 사용을 위한 openai 라이브러리
from bs4 import BeautifulSoup
import logging
import shutil
import json
import time

# 로그 설정
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def extract_arxiv_id(url: str) -> str:
    """URL에서 arXiv ID를 추출"""
    logging.debug(f"Extracting arXiv ID from URL: {url}")
    arxiv_id = url.split('/')[-1] if 'arxiv.org' in url else url
    logging.debug(f"Extracted arXiv ID: {arxiv_id}")
    return arxiv_id


def remove_latex_commands(text: str) -> str:
    # CJK* 관련 내용을 자동으로 대체
    text = re.sub(r'\\begin{CJK\*}\{.*?\}\{.*?\}', '', text)
    text = re.sub(r'\\end{CJK\*}', '', text)

    return text


def translate_text(text: str, paper_info: dict, chunk_size: int, target_language: str = "Korean") -> str:
    """Translates text using GPT API while preserving LaTeX structure and formatting."""
    paper_title = paper_info.get('title', '')
    paper_abstract = paper_info.get('abstract', '')

    cleaned_text = remove_latex_commands(text)
    logging.debug("Sending translation request to GPT API.")

    retry_attempts = 3  # Number of retry attempts
    for attempt in range(retry_attempts):
        try:
            response = openai.ChatCompletion.create(
                model="gpt-4o-mini",
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": f"""
                        You are an AI assistant specialized in translating academic papers in LaTeX format to {target_language}. Your task is to translate the content accurately while preserving the LaTeX structure and formatting. Pay close attention to technical terms and follow these guidelines meticulously.
                        Translation Instructions:

                        1. Translate the main content into {target_language}, preserving the structure and flow of the original text. Use an academic and formal tone appropriate for scholarly publications in {target_language}. Do not insert any arbitrary line breaks in the translated content.

                        2. Technical Terms:
                           a. Retain well-known technical terms, product names, or specialized concepts (e.g., Few-Shot Learning) in English.
                           b. Do not translate examples, especially if they contain technical content or are essential for context.

                        3. LaTeX Commands:
                           - Do not translate LaTeX commands, functions, environments, or specific LaTeX-related keywords (e.g., \section{{}}, \begin{{}}, \end{{}}, \cite{{}}, \ref{{}}, or TikZ syntax such as /tikz/fill, /tikz/draw, etc.) into {target_language}. They must be output exactly as they are.
                           - Only translate the provided text without making any additional modifications.

                        4. Citation and Reference Keys:
                           - Ensure all citation keys within \\cite{{}} and reference keys within \\ref{{}} remain unchanged. Do not translate or modify these keys.

                        5. URLs and DOIs:
                           - Do not translate URLs, DOIs, or any other links. Keep them in their original form.

                        6. Mathematical Equations and Formulas:
                           - Maintain all mathematical equations and formulas as they are in the original LaTeX. Do not translate code or LaTeX mathematical notation.

                        7. Names:
                           - Do not translate author names, personal names, or any other individual names. Keep these in their original English form.

                        8. Consistency:
                           - Ensure consistent terminology throughout the translation.

                        9. Protection of LaTeX Commands:
                            - Preserve line breaks (\\\\) and other formatting commands exactly as they appear in the original text.

                        10. Avoid Misleading Translations:
                            - Do not translate technical terms, product names, specialized concepts, examples, or personal names where translation could lead to a loss of meaning or context.

                        11. JSON Structure:
                            - Translate the content line by line, providing the translation in a JSON structure.
                            For example:
                              ```json
                              translate : {{
                                lines: [
                                "Translated Line 1",
                                "Translated Line 2"
                              ]}}
                              ```

                        ### Paper Info:
                        - Title : {paper_title}
                        - Abstract : {paper_abstract}
                        
                        ### Response Example:
                        #INPUT:
                        ["\\n", "\\documentclass{{article}} % For LaTeX2e\\n", "\\usepackage{{colm2024_conference}}\\n", "\\n", "\\usepackage{{microtype}}\\n"]
                        #OUTPUT:
                        {{"translate": {{"lines": ["\\n", "\\documentclass{{article}} % For LaTeX2e\\n", "\\usepackage{{colm2024_conference}}", "\\n", "\\usepackage{{microtype}}\\n"]}}}}
                        
                        ### VERY IMPORTANT
                        - DO NOT translate comments starting with "%" by arbitrarily merging them.
                        - DO NOT break a sentence into multiple paragraphs.
                        - Output the translated result in JSON format, without any other explanation.
                        - It should be translated and output in the same form as the unconditional input.
                        - Translate and output even single characters like '\\n', '{{', '/', '%', etc.
                        """
                     },
                    {"role": "user", "content": f"{cleaned_text}"}
                ]
            )

            translated_content = response.choices[0].message['content']
            translation_result = json.loads(translated_content)
            translation_lines = translation_result["translate"]['lines']
            translated_line_count = len(translation_lines)

            if translated_line_count != chunk_size:
                time.sleep(1)  # Optional: wait before retrying
                continue  # Retry the translation

            return ''.join(translation_lines)

        except Exception as error:
            logging.error(f"Error during translation attempt {attempt + 1}: {error}")
            if attempt == retry_attempts - 1:
                raise  # Re-raise the last exception after exhausting retries

    raise Exception("Translation failed after multiple attempts.")

def add_custom_font_to_tex(tex_file_path: str, font_name: str = "Noto Sans KR", mono_font_name: str = "Noto Sans KR"):
    """텍스트 파일에 사용자 지정 폰트를 추가"""
    logging.info(f"Adding custom font '{font_name}' to TeX file: {tex_file_path}")
    remove_cjk_related_lines(tex_file_path)
    font_setup = rf"""
        \usepackage{{kotex}}
        \usepackage{{xeCJK}}
        \setCJKmainfont{{{font_name}}}
        \setCJKmonofont{{{mono_font_name}}}
        \xeCJKsetup{{CJKspace=true}}
        """
    try:
        with open(tex_file_path, 'r+', encoding='utf-8') as file:
            lines = file.readlines()
            for i, line in enumerate(lines):
                if line.startswith(r'\documentclass'):
                    lines.insert(i + 1, font_setup)
                    break
            file.seek(0)
            file.writelines(lines)
        logging.debug("Custom font added successfully.")
    except Exception as e:
        logging.error(f"Failed to add custom font: {e}")
        raise


def remove_cjk_related_lines(tex_file_path: str):
    """텍스트 파일에서 CJK 관련 패키지와 설정을 제거"""
    logging.info(f"Removing CJK related lines from TeX file: {tex_file_path}")

    cjk_related_keywords = [
        r'\usepackage{CJKutf8}',
        r'\usepackage{kotex}',
        r'\begin{CJK}',
        r'\end{CJK}',
        r'\CJKfamily',
        r'\CJK@',
        r'\CJKrmdefault',
        r'\CJKsfdefault',
        r'\CJKttdefault',
    ]

    try:
        with open(tex_file_path, 'r+', encoding='utf-8') as file:
            lines = file.readlines()
            new_lines = []
            for line in lines:
                if not any(keyword in line for keyword in cjk_related_keywords):
                    new_lines.append(line)

            file.seek(0)
            file.writelines(new_lines)
            file.truncate()

        logging.debug("CJK related lines removed successfully.")
    except Exception as e:
        logging.error(f"Failed to remove CJK related lines: {e}")
        raise

def process_and_translate_tex_files(directory: str, paper_info: dict, read_lines: int = 30,
                                    target_language: str = "Korean", max_parallel_tasks: int = 8):
    """Processes .tex files by splitting them into chunks and translating them in parallel, ensuring error handling."""
    logging.info(f"Processing and translating lines in .tex files in directory: {directory}")

    file_line_chunks = []
    total_chunks = 0

    # Split files into chunks of lines and save to a list
    for root, _, files in os.walk(directory):
        for file in files:
            if file.endswith(".tex"):
                file_path = os.path.join(root, file)
                original_file_path = file_path + "_original"
                logging.info(f"Reading file: {file_path}")
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        lines = f.readlines()

                    # Save the original file with a different name
                    with open(original_file_path, 'w', encoding='utf-8') as original_f:
                        original_f.writelines(lines)

                    # Split the lines into safe chunks
                    chunks = chunk_lines_safely(lines, read_lines)

                    for idx, chunk in enumerate(chunks):
                        file_line_chunks.append((file_path, idx, chunk))
                    total_chunks += len(chunks)

                    # Save the modified file after removing comments or making other changes
                    with open(file_path, 'w', encoding='utf-8') as f:
                        f.writelines(lines)

                except Exception as e:
                    logging.error(f"Error reading or writing file {file_path}: {e}")

    if total_chunks == 0:
        logging.warning("No lines to translate.")
        return

    completed_chunks = 0

    # Translate each chunk in parallel
    def translate_chunk(file_chunk_info):
        nonlocal completed_chunks
        file_path, chunk_idx, chunk = file_chunk_info
        try:
            # Format the chunks as a list of dictionaries
            formatted_chunk = [line for idx, line in enumerate(chunk)]
            translated_text = translate_text(json.dumps(formatted_chunk), paper_info, len(chunk), target_language)
        except Exception as e:
            logging.error(f"Error translating chunk in file {file_path}: {e}")
            translated_text = ''.join(chunk)  # Return original text in case of an error

        completed_chunks += 1
        progress = (completed_chunks / total_chunks) * 100
        logging.info(f"Translation progress: {progress:.2f}% completed.")
        return (file_path, chunk_idx, translated_text)

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_parallel_tasks) as executor:
        translated_pairs = list(executor.map(translate_chunk, file_line_chunks))

    # Reassemble and save the translated content by file
    file_contents = {}
    for file_path, chunk_idx, translated_chunk in translated_pairs:
        if file_path not in file_contents:
            file_contents[file_path] = []
        file_contents[file_path].append((chunk_idx, translated_chunk))

    for file_path, chunks in file_contents.items():
        # Sort chunks by their original index
        sorted_chunks = sorted(chunks, key=lambda x: x[0])
        translated_content = ''.join(chunk for _, chunk in sorted_chunks)
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(translated_content)
            logging.info(f"File translated and saved: {file_path}")
        except Exception as e:
            logging.error(f"Error writing translated content to {file_path}: {e}")


def chunk_lines_safely(lines, lines_per_chunk):
    """
    Safely splits the given lines into chunks of a specified number of lines,
    excluding lines that are only newline characters.

    Args:
    - lines: List of all lines in the text.
    - lines_per_chunk: Number of lines to include in each chunk.

    Returns:
    - A list of chunks, where each chunk is a list of lines.
    """
    chunks = []
    current_chunk = []
    current_line_count = 0

    for line in lines:

        current_chunk.append(line)
        current_line_count += 1

        # If the specified number of lines is reached, save the current chunk and start a new one
        if current_line_count >= lines_per_chunk:
            chunks.append(current_chunk)
            current_chunk = []
            current_line_count = 0

    # If there are remaining lines, add them as the last chunk
    if current_chunk:
        chunks.append(current_chunk)

    return chunks


def extract_tar_gz(tar_file_path: str, extract_to: str):
    """tar.gz 파일을 지정된 디렉토리로 추출"""
    logging.info(f"Extracting tar.gz file: {tar_file_path} to {extract_to}")

    try:
        with tarfile.open(tar_file_path, 'r:gz') as tar_ref:
            tar_ref.extractall(path=extract_to)
        logging.debug("Extraction completed successfully.")
    except Exception as e:
        logging.error(f"Failed to extract tar.gz file: {e}")
        raise
def find_main_tex_file(directory: str) -> str:
    """디렉토리에서 'documentclass'를 포함한 main .tex 파일 찾기"""
    logging.info(f"Searching for main .tex file in directory: {directory}")

    candidate_files = []
    for root, _, files in os.walk(directory):
        for file in files:
            if file.endswith(".tex") and "_original" not in file:
                candidate_files.append(os.path.join(root, file))

    main_candidates = []
    for file in candidate_files:
        try:
            with open(file, 'r', encoding='utf-8') as f:
                contents = f.read()
                # \documentclass가 있는 파일을 찾기
                if r'\documentclass' in contents:
                    # 메인 파일인지 확인하기 위해 패키지 포함 여부와 환경 설정 등을 확인
                    if any(keyword in contents for keyword in [r'\begin{document}', r'\usepackage', r'\title', r'\author']):
                        logging.debug(f"Main candidate .tex file found: {file}")
                        main_candidates.append(file)
        except Exception as e:
            logging.error(f"Failed to read file {file}: {e}")

    # main 후보들 중 첫 번째 파일을 반환
    if main_candidates:
        logging.debug(f"Selected main .tex file: {main_candidates[0]}")
        return main_candidates[0]

    # 메인 파일 후보가 없으면, 크기가 가장 큰 .tex 파일 반환
    if candidate_files:
        main_tex = max(candidate_files, key=os.path.getsize, default=None)
        logging.debug(f"No clear main file found, selected by size: {main_tex}")
        return main_tex

    logging.warning("No .tex files found.")
    return None


def compile_main_tex(directory: str, arxiv_id: str, font_name: str = "Noto Sans KR"):
    """메인 .tex 파일을 컴파일하여 PDF 생성"""
    logging.info(f"Compiling main .tex file in directory: {directory}")

    main_tex_path = find_main_tex_file(directory)
    if main_tex_path:
        add_custom_font_to_tex(main_tex_path, font_name)
        compile_tex_to_pdf(main_tex_path, arxiv_id, compile_twice=True)
    else:
        logging.error("Main .tex file not found. Compilation aborted.")

def compile_tex_to_pdf(tex_file_path: str, arxiv_id: str, compile_twice: bool = True):
    """텍스트 파일을 PDF로 컴파일"""
    logging.info(f"Compiling TeX file to PDF: {tex_file_path}")

    tex_dir = os.path.dirname(tex_file_path)
    tex_file = os.path.basename(tex_file_path)

    try:
        for _ in range(2 if compile_twice else 1):
            result = subprocess.run(
                ['xelatex', '-interaction=nonstopmode',tex_file],
                cwd=tex_dir,
                encoding='utf-8'
            )
            logging.info(f"xelatex output: {result.stdout}")
            logging.info(f"xelatex errors: {result.stderr}")

        output_pdf = os.path.join(tex_dir, tex_file.replace(".tex", ".pdf"))
        if os.path.exists(output_pdf):
            current_dir = os.getcwd()
            final_pdf_path = os.path.join(current_dir, f"{arxiv_id}.pdf")
            os.rename(output_pdf, final_pdf_path)
            logging.info(f"PDF compiled and saved as: {final_pdf_path}")
        else:
            logging.error("PDF output not found after compilation.")
    except Exception as e:
        logging.error(f"Failed to compile TeX file: {e}")
        raise


def download_arxiv_intro_and_tex(arxiv_id: str, download_dir: str, target_language: str = "Korean",
                                 font_name: str = "Noto Sans KR"):
    """arXiv 논문 정보 및 텍스트 파일을 다운로드하고 번역"""
    logging.info(f"Downloading and processing arXiv paper: {arxiv_id}")

    arxiv_url = f"https://export.arxiv.org/api/query?id_list={arxiv_id}"

    try:
        response = requests.get(arxiv_url)
        response.raise_for_status()
    except requests.RequestException as e:
        logging.error(f"Failed to fetch arXiv metadata: {e}")
        raise

    soup = BeautifulSoup(response.content, 'xml')
    entry = soup.find('entry')
    if not entry:
        logging.error("ArXiv entry not found.")
        raise ValueError("ArXiv entry not found.")

    paper_info = {
        "title": entry.find('title').text,
        "abstract": entry.find('summary').text
    }
    logging.debug(f"Paper info: {paper_info}")

    tar_url = f"https://arxiv.org/src/{arxiv_id}"
    tar_file_path = os.path.join(download_dir, f"{arxiv_id}.tar.gz")

    os.makedirs(download_dir, exist_ok=True)

    try:
        with requests.get(tar_url, stream=True) as r:
            r.raise_for_status()
            with open(tar_file_path, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)
        logging.info(f"Downloaded tar.gz file: {tar_file_path}")
    except requests.RequestException as e:
        logging.error(f"Failed to download arXiv source tarball: {e}")
        raise

    extract_to = os.path.join(download_dir, arxiv_id)

    # 기존 arxiv_id 폴더가 존재하면 삭제
    if os.path.exists(extract_to):
        logging.info(f"Existing directory found: {extract_to}. Deleting it.")
        shutil.rmtree(extract_to)

    os.makedirs(extract_to, exist_ok=True)

    extract_tar_gz(tar_file_path, extract_to)
    process_and_translate_tex_files(extract_to, paper_info, target_language=target_language)
    compile_main_tex(extract_to, arxiv_id, font_name)

if __name__ == "__main__":
    # GPT API 호출을 위한 설정
    openai.api_key = 'OPENAI_API_KEY'  # 여기에 실제 API 키를 입력하세요.

    arxiv_input = input("Enter ArXiv ID or URL: ")
    arxiv_id = extract_arxiv_id(arxiv_input)
    download_dir = 'arxiv_downloads'
    download_arxiv_intro_and_tex(arxiv_id, download_dir, target_language="Korean", font_name="Noto Sans KR")

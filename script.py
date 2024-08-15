import subprocess
import os
import re
import tarfile
import requests
import openai  # GPT 사용을 위한 openai 라이브러리
from bs4 import BeautifulSoup
import logging

# 로그 설정
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def extract_arxiv_id(url: str) -> str:
    """URL에서 arXiv ID를 추출"""
    logging.debug(f"Extracting arXiv ID from URL: {url}")
    arxiv_id = url.split('/')[-1] if 'arxiv.org' in url else url
    logging.debug(f"Extracted arXiv ID: {arxiv_id}")
    return arxiv_id

def protect_latex_commands(text: str) -> str:
    """LaTeX 명령어들을 보호하기 위해 백슬래시를 이스케이프 처리"""
    logging.debug("Protecting LaTeX commands in the text.")
    return re.sub(r'(?<!\\)\\', r'\\\\', text)

def restore_latex_commands(text: str) -> str:
    """이스케이프 처리된 백슬래시를 원래 상태로 복원"""
    logging.debug("Restoring LaTeX commands in the text.")
    return re.sub(r'\\\\', r'\\', text)


def translate_text(text: str, paper_info: dict, target_language: str = "Korean") -> str:
    """GPT API를 사용해 텍스트 번역"""
    logging.info("Starting translation process...")
    title = paper_info.get('title', '')
    abstract = paper_info.get('abstract', '')

    protected_text = protect_latex_commands(text)
    logging.debug("Sending translation request to GPT API.")

    try:
        response = openai.ChatCompletion.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": f"""
                        You are an AI assistant specialized in translating academic papers in LaTeX format to {target_language}. Your task is to accurately translate the content while maintaining the LaTeX structure and formatting. Pay special attention to technical terms and follow these guidelines carefully.
                        
                        Follow these instructions for translation:
                        
                        1. Translate the main content to {target_language}, maintaining the overall structure and flow of the original text.
                        
                        2. For technical terms:
                           a. For well-known technical terms, product names, or specialized concepts (e.g., Few-Shot Learning), keep them in English without translation.
                           b. Do not translate examples, especially if they contain technical content or are integral to understanding the context.
                        
                        3. Do not translate any LaTeX commands, functions, environments, or specific LaTeX-related keywords. This includes commands like \\section{{}}, \\cite{{}}, \\ref{{}}, and any TikZ-related syntax like /tikz/fill, /tikz/draw, etc. Always keep all LaTeX-related syntax and keywords exactly as they appear in the original text.
                        
                        4. Ensure that all citation keys within \\cite{{}} and reference keys within \\ref{{}} remain unchanged and exactly as they are in the original text. Do not translate or modify these keys in any way.
                        
                        5. Do not translate URLs, DOIs, or any other links. Keep them in their original form.
                        
                        6. Maintain all mathematical equations and formulas as they are in the original LaTeX.
                        
                        7. Do not translate author names, personal names, or any other names of individuals. Keep these in their original English form.
                        
                        8. If there are any comments in the LaTeX code (starting with %% or %), translate the content of the comment but keep the %% or % symbol.
                        
                        9. Be consistent with terminology throughout the translation.
                        
                        10. Pay special attention to avoid any translation of LaTeX commands, TikZ options, formatting keywords, or environments. Ensure all LaTeX formatting commands and structures remain untouched and in English.
                        
                        11. Do not alter the number or placement of curly braces `{{}}` in LaTeX commands and environments. Ensure that every `{{` has a matching `}}` and do not add or remove any braces during translation.
                        
                        12. Do not close or add any LaTeX environments such as \\begin{{}} or \\end{{}}. Your task is solely to translate the text between these commands, leaving the LaTeX structure completely intact.
                        
                        13. If you encounter any ambiguous terms or phrases that you're unsure about, provide the best translation based on the context and add a translator's note in square brackets [].
                        
                        14. In all cases, avoid translating technical terms, product names, specialized concepts, examples, and personal names where translation could lead to a loss of meaning or context.
                        
                        Provide the translated content directly, without enclosing it in any additional tags or annotations.
                        
                        # Paper Info :
                        %% Title : {title}
                        %% Abstract : {abstract}
                        
                        Please only output the translated content directly.
                        Output the translation without enclosing it in any additional tags or annotations.
                        """
                },
                {"role": "user", "content": protected_text}
            ]
        )
        translated_data = response.choices[0].message['content'].strip()
        logging.debug("Translation completed.")
    except Exception as e:
        logging.error(f"Error during translation: {e}")
        raise

    restored_data = restore_latex_commands(translated_data)
    return restored_data

def add_custom_font_to_tex(tex_file_path: str, font_name: str = "KoPubWorldBatangPL", mono_font_name: str = "D2Coding", main_font_name: str = "Times New Roman"):
    """텍스트 파일에 사용자 지정 폰트를 추가"""
    logging.info(f"Adding custom font '{font_name}' to TeX file: {tex_file_path}")

    font_setup = rf"""
        \usepackage{{fontspec}}
        \setmainfont{{{main_font_name}}}
        \usepackage{{xeCJK}}
        \setCJKmainfont{{{font_name}}}
        \setCJKmonofont{{{mono_font_name}}}
        \xeCJKsetup{{CJKspace=true}}
        \usepackage{{microtype}}
        \AtBeginDocument{{\microtypesetup{{protrusion=true}}}}
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


def process_and_translate_tex_files(directory: str, paper_info: dict, read_lines: int = 60,
                                    target_language: str = "Korean"):
    """디렉토리 내의 모든 .tex 파일을 처리하고 번역"""
    logging.info(f"Processing and translating .tex files in directory: {directory}")

    tex_files = []
    for root, _, files in os.walk(directory):
        for file in files:
            if file.endswith(".tex"):
                tex_files.append(os.path.join(root, file))

    total_files = len(tex_files)
    if total_files == 0:
        logging.warning("No .tex files found in the directory.")
        return

    for idx, tex_file_path in enumerate(tex_files, start=1):
        logging.info(f"Processing file {idx}/{total_files}: {tex_file_path}")

        try:
            with open(tex_file_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()

            translated_lines = [
                translate_text(''.join(lines[i:i + read_lines]), paper_info, target_language)
                for i in range(0, len(lines), read_lines)
            ]

            with open(tex_file_path, 'w', encoding='utf-8') as f:
                f.write(''.join(translated_lines))
            logging.debug(f"File translated successfully: {tex_file_path}")
        except Exception as e:
            logging.error(f"Error processing file {tex_file_path}: {e}")

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
            if file.endswith(".tex"):
                candidate_files.append(os.path.join(root, file))

    for file in candidate_files:
        try:
            with open(file, 'r', encoding='utf-8') as f:
                contents = f.read()
                if r'\documentclass' in contents:
                    logging.debug(f"Main .tex file found: {file}")
                    return file
        except Exception as e:
            logging.error(f"Failed to read file {file}: {e}")

    if candidate_files:
        main_tex = max(candidate_files, key=os.path.getsize, default=None)
        logging.debug(f"Main .tex file selected by size: {main_tex}")
        return main_tex

    logging.warning("No .tex files found.")
    return None

def compile_main_tex(directory: str, arxiv_id: str, font_name: str = "KoPubWorldBatangPL"):
    """메인 .tex 파일을 컴파일하여 PDF 생성"""
    logging.info(f"Compiling main .tex file in directory: {directory}")

    main_tex_path = find_main_tex_file(directory)
    if main_tex_path:
        add_custom_font_to_tex(main_tex_path, font_name)
        compile_tex_to_pdf(main_tex_path, arxiv_id)
    else:
        logging.error("Main .tex file not found. Compilation aborted.")

def compile_tex_to_pdf(tex_file_path: str, arxiv_id: str):
    """텍스트 파일을 PDF로 컴파일"""
    logging.info(f"Compiling TeX file to PDF: {tex_file_path}")

    tex_dir = os.path.dirname(tex_file_path)
    tex_file = os.path.basename(tex_file_path)

    try:
        result = subprocess.run(['xelatex', '-interaction=nonstopmode', tex_file], cwd=tex_dir, capture_output=True, text=True)
        logging.debug(f"xelatex output: {result.stdout}")
        logging.debug(f"xelatex errors: {result.stderr}")

        output_pdf = os.path.join(tex_dir, tex_file.replace(".tex", ".pdf"))
        if os.path.exists(output_pdf):
            # 파이썬 실행 위치에 PDF 파일 저장
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
                                 font_name: str = "KoPubWorldBatangPL"):
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
    os.makedirs(extract_to, exist_ok=True)

    extract_tar_gz(tar_file_path, extract_to)
    process_and_translate_tex_files(extract_to, paper_info, target_language=target_language)
    compile_main_tex(extract_to, arxiv_id, font_name)
    compile_main_tex(extract_to, arxiv_id, font_name)

if __name__ == "__main__":
    # GPT API 호출을 위한 설정
    openai.api_key = 'OPENAI-API-KEY'  # 여기에 실제 API 키를 입력하세요.

    arxiv_input = input("Enter ArXiv ID or URL: ")
    arxiv_id = extract_arxiv_id(arxiv_input)
    download_dir = 'arxiv_downloads'
    download_arxiv_intro_and_tex(arxiv_id, download_dir, target_language="Korean", font_name="KoPubWorldBatangPL")
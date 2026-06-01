import pdfplumber
import openpyxl
import docx
from utils.file_types import UploadedFile


def extract_text_from_pdf(file: UploadedFile) -> str:
    """
    Extract text content from a PDF file-like object.

    :param file: File-like object with a `.filename` attribute and binary `.read()`.
    :return: The extracted text content.
    """
    with pdfplumber.open(file) as pdf:
        return "\n".join(page.extract_text() or "" for page in pdf.pages)


def extract_text_from_docx(file: UploadedFile) -> str:
    """
    Extract text content from a DOCX file-like object.

    :param file: File-like object with a `.filename` attribute and binary `.read()`.
    :return: The extracted text content.
    """
    doc = docx.Document(file)
    return "\n".join([para.text for para in doc.paragraphs])


def extract_text_from_txt(file: UploadedFile) -> str:
    """
    Extract text content from a plain text file-like object.

    :param file: File-like object with a `.filename` attribute and binary `.read()`.
    :return: The extracted text content.
    """
    return file.read().decode('utf-8')


def extract_text_from_xlsx(file: UploadedFile) -> str:
    """
    Extract text content from an Excel file (XLSX) file-like object.

    :param file: File-like object with a `.filename` attribute and binary `.read()`.
    :return: The extracted text content.
    """
    wb = openpyxl.load_workbook(file)
    text = []
    for sheet in wb.worksheets:
        for row in sheet.iter_rows(values_only=True):
            text.append("\t".join([str(cell) if cell is not None else "" for cell in row]))
    return "\n".join(text)


def extract_text_from_file(file: UploadedFile) -> str:
    """
    Extract text content from a file based on its extension.

    :param file: File-like object with a `.filename` attribute and binary `.read()`.
    :return: The extracted text content.
    """
    filename = file.filename.lower()
    if filename.endswith('.pdf'):
        return extract_text_from_pdf(file=file)
    elif filename.endswith('.docx'):
        return extract_text_from_docx(file=file)
    elif filename.endswith('.txt') or filename.endswith('.text') or filename.endswith('.md'):
        return extract_text_from_txt(file=file)
    elif filename.endswith('.xlsx') or filename.endswith('.xls') or filename.endswith('.xlsm') or filename.endswith('.xlt') or filename.endswith('.xltm'):
        return extract_text_from_xlsx(file=file)
    else:
        raise ValueError("Unsupported file type. Only PDF, DOCX, TXT, and MD are supported.")

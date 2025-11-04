import pdfplumber
import openpyxl
import docx


def extract_text_from_pdf(file):
    with pdfplumber.open(file) as pdf:
        return "\n".join(page.extract_text() or "" for page in pdf.pages)


def extract_text_from_docx(file):
    doc = docx.Document(file)
    return "\n".join([para.text for para in doc.paragraphs])


def extract_text_from_txt(file):
    return file.read().decode('utf-8')


def extract_text_from_xlsx(file):
    wb = openpyxl.load_workbook(file)
    text = []
    for sheet in wb.worksheets:
        for row in sheet.iter_rows(values_only=True):
            text.append("\t".join([str(cell) if cell is not None else "" for cell in row]))
    return "\n".join(text)


def extract_text_from_file(file):
    filename = file.filename.lower()
    if filename.endswith('.pdf'):
        return extract_text_from_pdf(file)
    elif filename.endswith('.docx'):
        return extract_text_from_docx(file)
    elif filename.endswith('.txt') or filename.endswith('.text') or filename.endswith('.md'):
        return extract_text_from_txt(file)
    elif filename.endswith('.xlsx') or filename.endswith('.xls') or filename.endswith('.xlsm') or filename.endswith('.xlt') or filename.endswith('.xltm'):
        return extract_text_from_xlsx(file)
    else:
        raise ValueError("Unsupported file type. Only PDF, DOCX, TXT, and MD are supported.")

from typing import List
import requests
import os
from datetime import datetime, timedelta
from ..paper import Paper
from .base import PaperSource
from .biorxiv import _extract_query_terms, _paper_matches
from pypdf import PdfReader

class MedRxivSearcher(PaperSource):
    """Searcher for medRxiv papers"""
    BASE_URL = "https://api.biorxiv.org/details/medrxiv"

    def __init__(self):
        self.session = requests.Session()
        self.session.proxies = {'http': None, 'https': None}
        self.timeout = 30
        self.max_retries = 3

    def search(self, query: str, max_results: int = 10, days: int = 30) -> List[Paper]:
        """
        Search for papers on medRxiv within the last N days, filtered by query keywords.

        与 bioRxiv 同理：details API 不支持关键词检索，直接把查询当分类会被忽略，
        导致不同主题返回同一批最新论文。改为拉取近 N 天论文后按关键词客户端过滤。

        Args:
            query: 检索关键词或布尔查询（用于客户端过滤）。
            max_results: 最大返回数。
            days: 回溯天数。
        """
        terms = _extract_query_terms(query)
        end_date = datetime.now().strftime('%Y-%m-%d')
        start_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')

        papers: List[Paper] = []
        cursor = 0
        fetch_cap = max(max_results * 5, 50)
        while len(papers) < max_results and cursor < fetch_cap:
            url = f"{self.BASE_URL}/{start_date}/{end_date}/{cursor}"
            tries = 0
            collected = 0
            while tries < self.max_retries:
                try:
                    response = self.session.get(url, timeout=self.timeout)
                    response.raise_for_status()
                    data = response.json()
                    collection = data.get('collection', [])
                    collected = len(collection)
                    for item in collection:
                        try:
                            title = item.get('title', '')
                            abstract = item.get('abstract', '')
                            if terms and not _paper_matches(title, abstract, terms):
                                continue
                            date = datetime.strptime(item['date'], '%Y-%m-%d')
                            papers.append(Paper(
                                paper_id=item['doi'],
                                title=title,
                                authors=item['authors'].split('; '),
                                abstract=abstract,
                                url=f"https://www.medrxiv.org/content/{item['doi']}v{item.get('version', '1')}",
                                pdf_url=f"https://www.medrxiv.org/content/{item['doi']}v{item.get('version', '1')}.full.pdf",
                                published_date=date,
                                updated_date=date,
                                source="medrxiv",
                                categories=[item.get('category', '')],
                                keywords=[],
                                doi=item['doi']
                            ))
                            if len(papers) >= max_results:
                                break
                        except Exception as e:
                            print(f"Error parsing medRxiv entry: {e}")
                    if collected < 100:
                        break  # No more results
                    cursor += 100
                    break  # Exit retry loop on success
                except requests.exceptions.RequestException as e:
                    tries += 1
                    if tries == self.max_retries:
                        print(f"Failed to connect to medRxiv API after {self.max_retries} attempts: {e}")
                        break
                    print(f"Attempt {tries} failed, retrying...")
            else:
                continue
            if collected < 100:
                break

        return papers[:max_results]

    def download_pdf(self, paper_id: str, save_path: str) -> str:
        """
        Download a PDF for a given paper ID from medRxiv.

        Args:
            paper_id: The DOI of the paper.
            save_path: Directory to save the PDF.

        Returns:
            Path to the downloaded PDF file.
        """
        if not paper_id:
            raise ValueError("Invalid paper_id: paper_id is empty")

        pdf_url = f"https://www.medrxiv.org/content/{paper_id}v1.full.pdf"
        tries = 0
        while tries < self.max_retries:
            try:
                # Add User-Agent to avoid potential 403 errors
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
                }
                response = self.session.get(pdf_url, timeout=self.timeout, headers=headers)
                response.raise_for_status()
                os.makedirs(save_path, exist_ok=True)
                output_file = f"{save_path}/{paper_id.replace('/', '_')}.pdf"
                with open(output_file, 'wb') as f:
                    f.write(response.content)
                return output_file
            except requests.exceptions.RequestException as e:
                tries += 1
                if tries == self.max_retries:
                    raise Exception(f"Failed to download PDF after {self.max_retries} attempts: {e}")
                print(f"Attempt {tries} failed, retrying...")
    
    def read_paper(self, paper_id: str, save_path: str = "./downloads") -> str:
        """
        Read a paper and convert it to text format.
        
        Args:
            paper_id: medRxiv DOI
            save_path: Directory where the PDF is/will be saved
            
        Returns:
            str: The extracted text content of the paper
        """
        pdf_path = f"{save_path}/{paper_id.replace('/', '_')}.pdf"
        if not os.path.exists(pdf_path):
            pdf_path = self.download_pdf(paper_id, save_path)
        
        try:
            reader = PdfReader(pdf_path)
            text = ""
            for page in reader.pages:
                text += page.extract_text() + "\n"
            return text.strip()
        except Exception as e:
            print(f"Error reading PDF for paper {paper_id}: {e}")
            return ""
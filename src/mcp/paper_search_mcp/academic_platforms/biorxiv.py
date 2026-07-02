from typing import List
import requests
import os
import re
from datetime import datetime, timedelta
from ..paper import Paper
from .base import PaperSource
from pypdf import PdfReader


def _extract_query_terms(query: str) -> List[str]:
    """从布尔查询或自然语言查询中提取有效检索词。

    bioRxiv/medRxiv 的 details API 不支持关键词检索，只能按日期范围+固定分类拉取最新论文。
    因此检索器在客户端对返回结果做关键词过滤：把用户的布尔查询（含 OR/AND/引号/括号）
    拆成独立检索词，再与论文标题/摘要做包含匹配。
    """
    if not query:
        return []
    cleaned = re.sub(r'["\'()]+', ' ', query)
    cleaned = re.sub(r'\b(AND|OR|NOT)\b', ' ', cleaned, flags=re.IGNORECASE)
    terms = [t.strip().lower() for t in re.split(r'[\s,]+', cleaned) if t.strip()]
    return [t for t in terms if len(t) >= 2]


def _paper_matches(paper_title: str, paper_abstract: str, terms: List[str]) -> bool:
    """论文标题或摘要是否包含任一检索词。"""
    if not terms:
        return False
    haystack = f"{paper_title or ''} {paper_abstract or ''}".lower()
    return any(term in haystack for term in terms)


class BioRxivSearcher(PaperSource):
    """Searcher for bioRxiv papers"""
    BASE_URL = "https://api.biorxiv.org/details/biorxiv"

    def __init__(self):
        self.session = requests.Session()
        self.session.proxies = {'http': None, 'https': None}
        self.timeout = 30
        self.max_retries = 3

    def search(self, query: str, max_results: int = 10, days: int = 30) -> List[Paper]:
        """
        Search for papers on bioRxiv within the last N days, filtered by query keywords.

        bioRxiv 的 details API 只支持按日期范围 + 固定分类（如 neuroscience）拉取论文，
        不支持关键词检索。直接把用户查询当 ``?category=`` 传会被忽略，导致不同主题都
        返回同一批最新论文。这里改为：拉取近 N 天论文后，按查询关键词在标题/摘要上
        做客户端过滤，匹配不上的不返回，避免污染结果。

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
        # 拉取上限：多拉一些再做关键词过滤，避免过滤后不足 max_results
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
                            # 客户端关键词过滤：不匹配查询词的论文直接跳过，
                            # 避免不同主题返回同一批最新论文
                            if terms and not _paper_matches(title, abstract, terms):
                                continue
                            date = datetime.strptime(item['date'], '%Y-%m-%d')
                            papers.append(Paper(
                                paper_id=item['doi'],
                                title=title,
                                authors=item['authors'].split('; '),
                                abstract=abstract,
                                url=f"https://www.biorxiv.org/content/{item['doi']}v{item.get('version', '1')}",
                                pdf_url=f"https://www.biorxiv.org/content/{item['doi']}v{item.get('version', '1')}.full.pdf",
                                published_date=date,
                                updated_date=date,
                                source="biorxiv",
                                categories=[item.get('category', '')],
                                keywords=[],
                                doi=item['doi']
                            ))
                            if len(papers) >= max_results:
                                break
                        except Exception as e:
                            print(f"Error parsing bioRxiv entry: {e}")
                    if collected < 100:
                        break  # No more results
                    cursor += 100
                    break  # Exit retry loop on success
                except requests.exceptions.RequestException as e:
                    tries += 1
                    if tries == self.max_retries:
                        print(f"Failed to connect to bioRxiv API after {self.max_retries} attempts: {e}")
                        break
                    print(f"Attempt {tries} failed, retrying...")
            else:
                continue
            if collected < 100:
                break

        return papers[:max_results]

    def download_pdf(self, paper_id: str, save_path: str) -> str:
        """
        Download a PDF for a given paper ID from bioRxiv.

        Args:
            paper_id: The DOI of the paper.
            save_path: Directory to save the PDF.

        Returns:
            Path to the downloaded PDF file.
        """
        if not paper_id:
            raise ValueError("Invalid paper_id: paper_id is empty")

        pdf_url = f"https://www.biorxiv.org/content/{paper_id}v1.full.pdf"
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
            paper_id: bioRxiv DOI
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
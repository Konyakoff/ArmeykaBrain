from pydantic import BaseModel, Field
from typing import List, Optional, Any

class ArticleItem(BaseModel):
    file_name: str
    section: str = ""
    subsection: str = ""
    item_number: str
    percent: int = 0

class Step1Result(BaseModel):
    articles: List[ArticleItem]
    query_category: str
    usage: Any = None
    in_tokens: int = 0
    out_tokens: int = 0
    prompt: str = ""
    error: Optional[str] = None

class Step2Result(BaseModel):
    answer: str
    usage: Any = None
    in_tokens: int = 0
    out_tokens: int = 0
    prompt: str = ""
    error: Optional[str] = None

class Step3Result(BaseModel):
    script: str
    usage: Any = None
    in_tokens: int = 0
    out_tokens: int = 0
    prompt: str = ""
    error: Optional[str] = None

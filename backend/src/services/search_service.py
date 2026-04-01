"""
Advanced Search and Filtering Service
Powerful search capabilities for clips, videos, and content.
"""

import re
import logging
from typing import Dict, Any, List, Optional, Set
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

logger = logging.getLogger(__name__)


class SearchField(Enum):
    """Fields available for search."""
    TITLE = "title"
    DESCRIPTION = "description"
    TRANSCRIPT = "transcript"
    TAGS = "tags"
    NICHE = "niche"
    PLATFORM = "platform"
    VIRALITY_SCORE = "virality_score"
    DURATION = "duration"
    CREATED_AT = "created_at"


class SortOrder(Enum):
    """Sort order options."""
    RELEVANCE = "relevance"
    VIRALITY_DESC = "virality_desc"
    VIRALITY_ASC = "virality_asc"
    DATE_DESC = "date_desc"
    DATE_ASC = "date_asc"
    DURATION_DESC = "duration_desc"
    DURATION_ASC = "duration_asc"


@dataclass
class SearchQuery:
    """Search query parameters."""
    query: str
    fields: List[SearchField]
    filters: Dict[str, Any]
    sort: SortOrder
    page: int
    per_page: int


@dataclass
class SearchResult:
    """Single search result."""
    item_id: str
    item_type: str  # clip, video, project
    title: str
    description: str
    score: float  # relevance/virality score
    matched_fields: List[str]
    highlight: Dict[str, str]  # highlighted snippets
    metadata: Dict[str, Any]


class SearchIndex:
    """
    In-memory search index for content.
    """
    
    def __init__(self):
        self._documents: Dict[str, Dict[str, Any]] = {}
        self._inverted_index: Dict[str, Set[str]] = {}
    
    def add_document(self, doc_id: str, document: Dict[str, Any]) -> None:
        """Add document to index."""
        self._documents[doc_id] = document
        
        # Index text fields
        text_fields = ["title", "description", "transcript", "tags"]
        
        for field in text_fields:
            if field in document:
                text = str(document[field]).lower()
                words = self._tokenize(text)
                
                for word in words:
                    if word not in self._inverted_index:
                        self._inverted_index[word] = set()
                    self._inverted_index[word].add(doc_id)
    
    def remove_document(self, doc_id: str) -> None:
        """Remove document from index."""
        if doc_id not in self._documents:
            return
        
        # Remove from inverted index
        for word, doc_ids in self._inverted_index.items():
            doc_ids.discard(doc_id)
        
        # Remove document
        del self._documents[doc_id]
    
    def _tokenize(self, text: str) -> List[str]:
        """Tokenize text for indexing."""
        # Simple tokenization
        words = re.findall(r'\b[a-z]{3,}\b', text)
        return words
    
    def search(self, query: str, fields: Optional[List[str]] = None) -> Set[str]:
        """Search for documents matching query."""
        query_words = self._tokenize(query.lower())
        
        if not query_words:
            return set()
        
        # Find documents containing query words
        results = None
        
        for word in query_words:
            matching_docs = self._inverted_index.get(word, set())
            
            if results is None:
                results = matching_docs
            else:
                # AND operation - all words must be present
                results = results & matching_docs
        
        return results or set()
    
    def get_document(self, doc_id: str) -> Optional[Dict[str, Any]]:
        """Get document by ID."""
        return self._documents.get(doc_id)


class AdvancedSearchService:
    """
    Advanced search with filtering and faceting.
    """
    
    def __init__(self):
        self.index = SearchIndex()
    
    def index_clip(
        self,
        clip_id: str,
        clip_data: Dict[str, Any]
    ) -> None:
        """Index a clip for search."""
        document = {
            "id": clip_id,
            "type": "clip",
            "title": clip_data.get("title", ""),
            "description": clip_data.get("description", ""),
            "transcript": clip_data.get("transcript", ""),
            "tags": " ".join(clip_data.get("tags", [])),
            "niche": clip_data.get("niche", ""),
            "platform": clip_data.get("platform", ""),
            "virality_score": clip_data.get("virality_score", 0),
            "duration": clip_data.get("duration", 0),
            "created_at": clip_data.get("created_at", ""),
            "metadata": clip_data
        }
        
        self.index.add_document(clip_id, document)
        logger.debug(f"Indexed clip: {clip_id}")
    
    def search(
        self,
        query: str,
        filters: Optional[Dict[str, Any]] = None,
        sort: SortOrder = SortOrder.RELEVANCE,
        page: int = 1,
        per_page: int = 20
    ) -> Dict[str, Any]:
        """
        Perform advanced search with filters.
        
        Args:
            query: Search query string
            filters: Optional filters (niche, platform, min_virality, etc.)
            sort: Sort order
            page: Page number (1-based)
            per_page: Items per page
        """
        filters = filters or {}
        
        # Get base results from index
        matching_ids = self.index.search(query)
        
        if not matching_ids:
            return {
                "results": [],
                "total": 0,
                "page": page,
                "per_page": per_page,
                "total_pages": 0
            }
        
        # Apply filters
        filtered_results = []
        
        for doc_id in matching_ids:
            doc = self.index.get_document(doc_id)
            
            if not doc:
                continue
            
            # Apply filters
            if self._matches_filters(doc, filters):
                # Calculate relevance score
                score = self._calculate_score(doc, query)
                
                # Create result
                result = SearchResult(
                    item_id=doc_id,
                    item_type=doc["type"],
                    title=doc.get("title", ""),
                    description=doc.get("description", ""),
                    score=score,
                    matched_fields=self._get_matched_fields(doc, query),
                    highlight=self._create_highlights(doc, query),
                    metadata=doc.get("metadata", {})
                )
                
                filtered_results.append(result)
        
        # Sort results
        sorted_results = self._sort_results(filtered_results, sort)
        
        # Paginate
        total = len(sorted_results)
        start_idx = (page - 1) * per_page
        end_idx = start_idx + per_page
        paginated = sorted_results[start_idx:end_idx]
        
        total_pages = (total + per_page - 1) // per_page
        
        return {
            "results": [
                {
                    "item_id": r.item_id,
                    "item_type": r.item_type,
                    "title": r.title,
                    "description": r.description,
                    "score": r.score,
                    "matched_fields": r.matched_fields,
                    "highlight": r.highlight,
                    "metadata": r.metadata
                }
                for r in paginated
            ],
            "total": total,
            "page": page,
            "per_page": per_page,
            "total_pages": total_pages,
            "facets": self._get_facets(sorted_results)
        }
    
    def _matches_filters(
        self,
        doc: Dict[str, Any],
        filters: Dict[str, Any]
    ) -> bool:
        """Check if document matches all filters."""
        # Niche filter
        if "niche" in filters:
            if doc.get("niche") != filters["niche"]:
                return False
        
        # Platform filter
        if "platform" in filters:
            if doc.get("platform") != filters["platform"]:
                return False
        
        # Min virality score
        if "min_virality" in filters:
            if doc.get("virality_score", 0) < filters["min_virality"]:
                return False
        
        # Duration range
        if "min_duration" in filters:
            if doc.get("duration", 0) < filters["min_duration"]:
                return False
        
        if "max_duration" in filters:
            if doc.get("duration", float('inf')) > filters["max_duration"]:
                return False
        
        # Date range
        if "created_after" in filters:
            if doc.get("created_at", "") < filters["created_after"]:
                return False
        
        if "created_before" in filters:
            if doc.get("created_at", "") > filters["created_before"]:
                return False
        
        return True
    
    def _calculate_score(
        self,
        doc: Dict[str, Any],
        query: str
    ) -> float:
        """Calculate relevance score for document."""
        score = 0.0
        query_lower = query.lower()
        
        # Title match (highest weight)
        title = doc.get("title", "").lower()
        if query_lower in title:
            score += 10.0
            if title.startswith(query_lower):
                score += 5.0
        
        # Description match
        desc = doc.get("description", "").lower()
        if query_lower in desc:
            score += 5.0
        
        # Transcript match
        transcript = doc.get("transcript", "").lower()
        count = transcript.count(query_lower)
        score += count * 2.0
        
        # Virality bonus
        virality = doc.get("virality_score", 0)
        score += virality * 0.1
        
        return score
    
    def _get_matched_fields(
        self,
        doc: Dict[str, Any],
        query: str
    ) -> List[str]:
        """Get fields that matched the query."""
        matched = []
        query_lower = query.lower()
        
        field_map = {
            "title": doc.get("title", ""),
            "description": doc.get("description", ""),
            "transcript": doc.get("transcript", ""),
            "tags": doc.get("tags", "")
        }
        
        for field, value in field_map.items():
            if query_lower in str(value).lower():
                matched.append(field)
        
        return matched
    
    def _create_highlights(
        self,
        doc: Dict[str, Any],
        query: str
    ) -> Dict[str, str]:
        """Create highlighted snippets for matched fields."""
        highlights = {}
        query_lower = query.lower()
        
        for field in ["title", "description", "transcript"]:
            value = doc.get(field, "")
            if query_lower in str(value).lower():
                # Extract snippet around match
                idx = str(value).lower().find(query_lower)
                start = max(0, idx - 50)
                end = min(len(value), idx + len(query) + 50)
                snippet = value[start:end]
                
                # Highlight
                highlighted = snippet.replace(
                    query,
                    f"<mark>{query}</mark>"
                )
                
                highlights[field] = f"...{highlighted}..."
        
        return highlights
    
    def _sort_results(
        self,
        results: List[SearchResult],
        sort: SortOrder
    ) -> List[SearchResult]:
        """Sort search results."""
        if sort == SortOrder.RELEVANCE:
            return sorted(results, key=lambda x: x.score, reverse=True)
        
        elif sort == SortOrder.VIRALITY_DESC:
            return sorted(
                results,
                key=lambda x: x.metadata.get("virality_score", 0),
                reverse=True
            )
        
        elif sort == SortOrder.VIRALITY_ASC:
            return sorted(
                results,
                key=lambda x: x.metadata.get("virality_score", 0)
            )
        
        elif sort == SortOrder.DATE_DESC:
            return sorted(
                results,
                key=lambda x: x.metadata.get("created_at", ""),
                reverse=True
            )
        
        elif sort == SortOrder.DATE_ASC:
            return sorted(
                results,
                key=lambda x: x.metadata.get("created_at", "")
            )
        
        elif sort == SortOrder.DURATION_DESC:
            return sorted(
                results,
                key=lambda x: x.metadata.get("duration", 0),
                reverse=True
            )
        
        elif sort == SortOrder.DURATION_ASC:
            return sorted(
                results,
                key=lambda x: x.metadata.get("duration", 0)
            )
        
        return results
    
    def _get_facets(self, results: List[SearchResult]) -> Dict[str, Any]:
        """Get facet counts for filtering."""
        facets = {
            "niche": {},
            "platform": {},
            "virality_ranges": {
                "high": 0,    # 80-100
                "medium": 0,  # 50-79
                "low": 0      # 0-49
            }
        }
        
        for result in results:
            meta = result.metadata
            
            # Niche facet
            niche = meta.get("niche", "unknown")
            facets["niche"][niche] = facets["niche"].get(niche, 0) + 1
            
            # Platform facet
            platform = meta.get("platform", "unknown")
            facets["platform"][platform] = facets["platform"].get(platform, 0) + 1
            
            # Virality range
            score = meta.get("virality_score", 0)
            if score >= 80:
                facets["virality_ranges"]["high"] += 1
            elif score >= 50:
                facets["virality_ranges"]["medium"] += 1
            else:
                facets["virality_ranges"]["low"] += 1
        
        return facets
    
    def get_suggestions(self, partial: str, limit: int = 10) -> List[str]:
        """Get search suggestions based on partial input."""
        partial_lower = partial.lower()
        suggestions = []
        
        # Find indexed terms starting with partial
        for term in self.index._inverted_index.keys():
            if term.startswith(partial_lower) and len(term) > len(partial_lower):
                suggestions.append(term)
                
                if len(suggestions) >= limit:
                    break
        
        return sorted(suggestions)


# Global instance
_search_service: Optional[AdvancedSearchService] = None


def get_search_service() -> AdvancedSearchService:
    """Get global search service."""
    global _search_service
    if _search_service is None:
        _search_service = AdvancedSearchService()
    return _search_service


# Convenience functions
def search_clips(
    query: str,
    filters: Optional[Dict[str, Any]] = None,
    sort: str = "relevance",
    page: int = 1,
    per_page: int = 20
) -> Dict[str, Any]:
    """Search clips with filters."""
    service = get_search_service()
    
    sort_order = SortOrder(sort) if sort in [s.value for s in SortOrder] else SortOrder.RELEVANCE
    
    return service.search(query, filters, sort_order, page, per_page)


def index_clip_for_search(clip_id: str, clip_data: Dict[str, Any]) -> None:
    """Index a clip for search."""
    get_search_service().index_clip(clip_id, clip_data)

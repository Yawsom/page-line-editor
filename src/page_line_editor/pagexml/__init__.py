"""Secure PAGE 2013 parsing, narrow writing, and validation."""

from .parser import PAGE_2013_NAMESPACE, PageXmlError, parse_page
from .validator import Severity, ValidationIssue, ValidationReport, validate_document, validate_xml
from .writer import build_candidate

__all__ = [
    "PAGE_2013_NAMESPACE",
    "PageXmlError",
    "Severity",
    "ValidationIssue",
    "ValidationReport",
    "build_candidate",
    "parse_page",
    "validate_document",
    "validate_xml",
]

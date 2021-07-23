import itertools
import logging

from typing import List, Any, Tuple, Dict
from typing_extensions import TypedDict

import ckan.plugins.toolkit as tk
import ckan.plugins as p
from ckan.lib.search.query import solr_literal

from ckanext.search_autocomplete.interfaces import ISearchAutocomplete

CONFIG_AUTOCOMPLETE_LIMIT = "ckanext.search_autocomplete.autocomplete_limit"
CONFIG_IGNORE_SYNONYMS = "ckanext.search_autocomplete.ignore_synonyms"

DEFAULT_AUTOCOMPLETE_LIMIT = 6
DEFAULT_IGNORE_SYNONYMS = False

log = logging.getLogger(__name__)


class Suggestion(TypedDict):
    href: str
    label: str
    type: str
    count: int


def _get_autocomplete_limit():
    return tk.asint(
        tk.config.get(CONFIG_AUTOCOMPLETE_LIMIT, DEFAULT_AUTOCOMPLETE_LIMIT)
    )


def autocomplete_datasets(terms: List[str]) -> List[Suggestion]:
    """Return limited number of autocomplete suggestions."""
    combined, *others = _datasets_by_terms(terms, include_combined=True)

    # Combine and dedup all the results
    other: List[Dict[str, str]] = [
        item
        for item, _ in itertools.groupby(
            sorted(
                filter(None, itertools.chain(*itertools.zip_longest(*others))),
                key=lambda i: i["title"],
            )
        )
        if item not in combined
    ]

    return [
        Suggestion(
            href=tk.h.url_for("dataset.read", id=item["name"]),
            label=item["title"],
            type="Dataset",
            count=1,
        )
        for item in combined
        + other[: _get_autocomplete_limit() - len(combined)]
    ]


def _datasets_by_terms(
    terms: List[str],
    include_combined: bool = False,
    limit: int = _get_autocomplete_limit(),
) -> List[List[Dict[str, str]]]:
    """Get list of search result iterables.

    When include_combined is set to True, prepend list with results from
    combined search for all the terms, i.e results that includes every term from
    the list of provided values. Can be used for building more relevant
    suggestions.

    """
    terms = [solr_literal(term) for term in terms]
    if include_combined:

        terms = [" ".join(terms)] + terms

    ignore_synonyms = tk.asbool(tk.config.get(CONFIG_IGNORE_SYNONYMS, DEFAULT_IGNORE_SYNONYMS))
    if ignore_synonyms:
        fq = "title_ngram:({0})"
    else:
        fq = "title:({0}) OR title_ngram:({0})"

    return [
        tk.get_action("package_search")(
            {},
            {
                "include_private": True,
                "rows": limit,
                "fl": "name,title",
                "fq": fq.format(term),
            },
        )["results"]
        for term in terms
    ]


def autocomplete_categories(terms: List[str]) -> List[Suggestion]:
    facets = tk.get_action("package_search")(
        {},
        {
            "rows": 0,
            "facet.field": list(get_categories().keys()),
        },
    )["search_facets"]

    categories: List[List[Dict[str, Any]]] = []
    for facet in facets.values():
        group: List[Tuple[int, Dict[str, Any]]] = []
        for item in facet["items"]:
            # items with highest number of matches will have higher priority in
            # suggestion list
            matches = 0
            for term in terms:
                if term in item["display_name"].lower():
                    matches += 1
            if not matches:
                continue

            group.append(
                (
                    matches,
                    Suggestion(
                        href=tk.h.url_for(
                            "dataset.search", **{facet["title"]: item["name"]}
                        ),
                        label=item["display_name"],
                        type=get_categories()[facet["title"]],
                        count=item["count"],
                    ),
                )
            )
        categories.append(
            [
                item
                for _, item in sorted(
                    group, key=lambda i: (i[0], i[1]["count"]), reverse=True
                )
            ]
        )
    return list(
        sorted(
            itertools.islice(
                filter(
                    None, itertools.chain(*itertools.zip_longest(*categories))
                ),
                _get_autocomplete_limit(),
            ),
            key=lambda item: item["type"],
        )
    )


def get_categories():

    for plugin in p.PluginImplementations(ISearchAutocomplete):
        categories = plugin.get_categories()
        break
    else:
        categories = {
            "organization": tk._("Organisations"),
            "tags": tk._("Tags"),
            "res_format": tk._("Formats"),
        }

    return categories

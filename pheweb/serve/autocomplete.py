

from .. import utils
conf = utils.conf

import itertools
import re
import marisa_trie
import copy
import os

# TODO: sort suggestions better.
# - It's good that hitting enter sends you to the thing with the highest token-ratio.
# - But it's not good that that's not the first thing in the autocomplete suggestions.
# - Solution:
#     - for rsid and variant, the list should be sorted first by length.
#     - for stringy things, the list should be sorted by token-match-ratio.  That's gonna suck to implement in javascript.
#         - Could we send token-sort-ratio along and tell typeaheadjs to sort on it? No, b/c the query changes.
#         - but, stringy things should just be in a streamtable anyways.


class Autocompleter(object):
    def __init__(self, phenos):
        self._phenos = copy.deepcopy(phenos)
        self._preprocess_phenos()

        self._cpra_to_rsids_trie = marisa_trie.BytesTrie().load(conf.data_dir + '/sites/cpra_to_rsids_trie.marisa')
        self._rsid_to_cpra_trie = marisa_trie.BytesTrie().load(conf.data_dir + '/sites/rsid_to_cpra_trie.marisa')
        self._gene_alias_trie = marisa_trie.BytesTrie().load(utils.get_cacheable_file_location(os.path.join(conf.data_dir, 'sites', 'genes'), 'gene_aliases.marisa_trie'))

        self._autocompleters = [
            self._autocomplete_variant,
            self._autocomplete_rsid,
            self._autocomplete_phenocode,
            self._autocomplete_gene,
        ]
        if any('phenostring' in pheno for pheno in self._phenos.values()):
            self._autocompleters.append(self._autocomplete_phenostring)
        if any('icd9_info' in pheno for pheno in self._phenos.values()):
            self._autocompleters.extend([
                self._autocomplete_icd9_code,
                self._autocomplete_icd9_string,
            ])

    def autocomplete(self, query):
        query = query.strip()
        result = []
        for autocompleter in self._autocompleters:
            result = list(itertools.islice(autocompleter(query), 0, 10))
            if result: break
        return result

    def get_best_completion(self, query):
        # TODO: get_autocompletion only returns the first 10, so this will be a little broken.  Look at more.
        suggestions = self.autocomplete(query)
        if not suggestions:
            return None
        query_tokens = query.strip().lower().split()
        for suggestion in suggestions:
            suggestion_tokens = suggestion['display'].lower().split()
            intersection_tokens = set(query_tokens).intersection(suggestion_tokens)
            suggestion['match_quality'] = len(intersection_tokens) / len(suggestion_tokens)
        return max(suggestions, key=lambda sugg: sugg['match_quality'])


    _process_string_non_word_regex = re.compile(r"(?ui)[^\w\.]") # Most of the time we want to include periods in words
    @classmethod
    def _process_string(cls, string):
        # Cleaning inspired by <https://github.com/seatgeek/fuzzywuzzy/blob/6353e2/fuzzywuzzy/utils.py#L69>
        return ' ' + cls._process_string_non_word_regex.sub(' ', string).lower().strip()

    def _preprocess_phenos(self):
        for phenocode, pheno in self._phenos.items():
            pheno['--spaced--phenocode'] = self._process_string(phenocode)
            if 'phenostring' in pheno:
                pheno['--spaced--phenostring'] = self._process_string(pheno['phenostring'])
            if 'icd9_info' in pheno:
                for icd9 in pheno['icd9_info']:
                    icd9['--spaced--icd9_string'] = self._process_string(icd9['icd9_string'])


    def _autocomplete_variant(self, query):
        # chrom-pos-ref-alt format
        query = query.replace(',', '')
        chrom, pos, ref, alt = utils.variant_parser.parse(query, default_chrom_pos = False)
        if chrom is not None:
            key = '-'.join(str(e) for e in [chrom,pos,ref,alt] if e is not None)
            for cpra, rsids in self._cpra_to_rsids_trie.iteritems(key):
                cpra = cpra.replace('-', ':', 1)
                rsids = rsids.decode('ascii')
                yield {
                    "value": cpra,
                    "display": '{} ({})'.format(cpra, rsids) if rsids else cpra,
                    "url": "/variant/{}".format(cpra)
                }

    def _autocomplete_rsid(self, query):
        query = query.lower()
        if query.startswith('rs'):
            key = query

            # In Trie.iteritems, "rs100" comes before "rs1".
            # So, rsid_to_cpra_trie.iteritems("rs7412")[-1] is "rs7412".
            # That's unfortunate, and I don't know how to fix it.
            # I wish we could get a real lexicographic order, where shorter strings come first, but I don't see how.
            # Even better would be to the 10 shortest children of the current string.
            # Here's an attempt at being a little better.

            rsids_to_check = [key] + ["{}{}".format(key, i) for i in range(10)]
            for rsid in rsids_to_check:
                cpra = self._rsid_to_cpra_trie.get(rsid)
                if cpra is not None:
                    cpra = cpra[0]
                    cpra = cpra.decode('ascii').replace('-', ':', 1)
                    yield {
                        "value": cpra,
                        "display": '{} ({})'.format(rsid, cpra),
                        "url": "/variant/{}".format(cpra)
                    }

            for rsid, cpra in self._rsid_to_cpra_trie.iteritems(key):
                if rsid not in rsids_to_check: # don't repeat rsids we already yeld.
                    cpra = cpra.decode('ascii').replace('-', ':', 1)
                    yield {
                        "value": cpra,
                        "display": '{} ({})'.format(rsid, cpra),
                        "url": "/variant/{}".format(cpra)
                    }

    def _autocomplete_phenocode(self, query):
        query = self._process_string(query)
        for phenocode, pheno in self._phenos.items():
            if query in pheno['--spaced--phenocode']:
                yield {
                    "value": phenocode,
                    "display": "{} ({})".format(phenocode, pheno['phenostring']) if 'phenostring' in pheno else phenocode, # TODO: truncate phenostring intelligently
                    "url": "/pheno/{}".format(phenocode),
                }

    def _autocomplete_phenostring(self, query):
        query = self._process_string(query)
        for phenocode, pheno in self._phenos.items():
            if query in pheno['--spaced--phenostring']:
                yield {
                    "value": phenocode,
                    "display": "{} ({})".format(pheno['phenostring'], phenocode),
                    "url": "/pheno/{}".format(phenocode),
                }

    def _autocomplete_gene(self, query):
        key = query.upper()
        if len(key) >= 2:

            for alias, canonical_symbol in self._gene_alias_trie.iteritems(key):
                canonical_symbol = canonical_symbol.decode('ascii')
                if ',' in canonical_symbol:
                    yield {
                        'value': canonical_symbol.split(',')[0],
                        'display': '{} (alias for {})'.format(alias, ' and '.join(canonical_symbol.split(','))),
                        'url': '/error/the gene {} is connected to the genes {}'.format(alias, ' and '.join(canonical_symbol.split(','))),
                    }
                elif canonical_symbol == alias:
                    yield {
                        "value": canonical_symbol,
                        "display": canonical_symbol,
                        "url": "/gene/{}".format(canonical_symbol),
                    }
                else:
                    yield {
                        "value": canonical_symbol,
                        "display": '{} (alias for {})'.format(alias, canonical_symbol),
                        "url": "/gene/{}".format(canonical_symbol),
                    }

    _regex_get_icd9_code_autocompletion = re.compile('^\s*V?[0-9]')
    def _autocomplete_icd9_code(self, query):
        if self._regex_get_icd9_code_autocompletion.match(query):
            for phenocode, pheno in self._phenos.items():
                for icd9 in pheno['icd9_info']:
                    if icd9['icd9_code'].startswith(query):
                        yield {
                            "value": phenocode,
                            "display": "{} (icd9 code; phewas code: {}; icd9_string: {})".format(icd9['icd9_code'], phenocode, icd9['icd9_string']),
                            "url": "/pheno/{}".format(phenocode),
                        }

    _regex_get_icd9_string_autocompletion = re.compile('^\s*[a-zA-Z]')
    def _autocomplete_icd9_string(self, query):
        query = self._process_string(query)
        if self._regex_get_icd9_string_autocompletion.match(query):
            for phenocode, pheno in self._phenos.items():
                for icd9 in pheno.get('icd9_info', []):
                    if query in icd9['--spaced--icd9_string']:
                        yield {
                            "value": phenocode,
                            "display": "{} (icd9 string; icd9 code: {}; phewas code: {})".format(icd9['icd9_string'], icd9['icd9_code'], phenocode),
                            "url": "/pheno/{}".format(phenocode),
                        }

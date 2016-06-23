#!/bin/bash

set -euo pipefail

PROJECT_DIR="$( cd "$( dirname "$( dirname "$(readlink -f "${BASH_SOURCE[0]}" )" )" )" && pwd )"
source "$PROJECT_DIR/config.config"

export PATH="$bedtools_path:$PATH"

if [[ -e "$data_dir/sites/cpra_rsids.lexicographic.vcf" ]]; then
    echo "$data_dir/sites/cpra_rsids.lexicographic.vcf" already exists.
else
    # bedtools needs these headers, including a INFO column.
    echo '##fileformat=VCFv4.0' > "$data_dir/sites/cpra_rsids.lexicographic.vcf"
    echo -e '#CHROM\tPOS\tREF\tALT\tID\tINFO' >> "$data_dir/sites/cpra_rsids.lexicographic.vcf"

    # bedtools needs this sort order.
    cat "$data_dir/sites/cpra_rsids.tsv" |
    sort -k 1,1 -k2,2n |
    perl -ple '$_ .= "\t."' \
    >> "$data_dir/sites/cpra_rsids.lexicographic.vcf"
fi

bedtools closest -D ref -a "$data_dir/sites/cpra_rsids.lexicographic.vcf" -b "$data_dir/sites/genes/genes.lexicographic.bed" |
perl -F'\t' -nale 'print "$F[0]\t$F[1]\t$F[2]\t$F[3]\t$F[4]\t$F[9]\t$F[10]"' \
> "$data_dir/sites/cpra_rsids_genes.lexicographic.tsv"

echo done!
#/usr/bin/env bash
find .data -name "*.json" | xargs perl -lne 'print $1 if /"speaker": "(.*)"/' | sort | uniq -c | sort -rn > data/speakers.txt

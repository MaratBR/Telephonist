#!/bin/bash

ID=$(hexdump -vn16 -e'4/4 "%08X" 1 "\n"' /dev/urandom)
TMP_FOLDER=/tmp/gettext_tmp_$ID

function update_locales_folder {
  directory=$1
  po_files=
  for po_file in $directory/LC_MESSAGES/* ; do
    if [[ "${po_file##*.}" == "pot" ]]; then
      tmp_file=$TMP_FOLDER/$(basename $po_file).new
      echo "Processing $po_file ..."
      pygettext3 -d messages -o $tmp_file server/**/*.py >/dev/null
      msgmerge $po_file $tmp_file >$TMP_FOLDER/buffer
      cp $TMP_FOLDER/buffer $po_file
    fi
  done
}

mkdir $TMP_FOLDER

for i in locales/* ; do
  update_locales_folder $i
done

rm -r $TMP_FOLDER

#chains A (ace2) and B (spike) of 6LZG PDB ID
#crystallographic water and NAG removed 

#self scan
mutatex 6LZGab_noHOH.pdb --np 4 
                         -s \
                         -q poslist.txt \
			 -m mutation_list.txt \
			 -x /usr/local/foldx5_2021/foldx \
			 --foldx-version=suite5 \
			 -B \
			 -C deep \
			 -v \
			 -L \
			 -c \
			 -l

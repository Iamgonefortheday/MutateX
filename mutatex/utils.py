#!/usr/bin/env python

#    utils.py: miscellaneous utilities for MutateX plotting scripts
#    Copyright (C) 2015, Matteo Tiberti <matteo.tiberti@gmail.com>
#                        Thilde Bagger Terkelsen <ThildeBT@gmail.com>
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.

import numpy as np
import logging as log
from six import iteritems
from Bio import PDB
from multiprocessing.pool import ThreadPool
import matplotlib
import sys
import os
import signal
import argparse
import multiprocessing as mp
import logging as log
import shutil
import re
import numpy as np
import tarfile as tar
import platform
import textwrap
import csv

def init_arguments(arguments, parser):
    """
    Adds arguments common to several mutatex scripts to a argparse.ArgumentParser
    instance. Arguments are specified by name.
    Parameters
    ----------
    arguments : arguments.ArgumentParser instance or any object with the ``add_argument`` method
        instance to which options will be added
    parser : iterable of str
        list of names for the arguments to be added
    Returns
    -------
    parser : arguments.ArgumentParser instance or any object with the ``add_argument`` method
        the same object of the input parameter, modified with additional arguments
    """

    assert len(set(arguments)) == len(arguments)

    for arg in arguments:
        if   arg == 'pdb':
            parser.add_argument("-p","--pdb", dest="in_pdb", help="Input PDB file", required=True)
        elif arg == 'data':
            parser.add_argument("-d","--data-directory", dest="ddg_dir", type=str, help="Input DDG data directory", required=True)
        elif arg == 'mutation_list':
            parser.add_argument("-l","--mutation-list", dest="mutation_list",  help="MutateX mutation list file", required=True)
        elif arg == 'position_list':
            parser.add_argument("-q","--position-list", dest="position_list",  help="MutateX position list file", default=None)
        elif arg == 'multimers':
            parser.add_argument("-M","--multimers", dest="multimers", default=True, action='store_false', help="Do not use multimers (default: yes)")
        elif arg == 'labels':
            parser.add_argument("-b","--label-list", dest="labels", help="Residue label list")
        elif arg == 'fonts':
            parser.add_argument("-F","--font", dest='font',action='store', type=str, default=None, help="Use this font for plotting. If this isn't specified, the default font will be used.")
        elif arg == 'fontsize':
            parser.add_argument("-f","--fontsize",dest='fontsize',action='store', type=int, default=8, help="Axis label font size")
        elif arg == 'verbose':
            parser.add_argument("-v","--verbose", dest="verbose", action="store_true", default=False, help="Toggle verbose mode")
        elif arg == 'title':
            parser.add_argument("-i","--title", dest='title', type=str, default=None, help="Title for the output image file")
        elif arg == 'color':
            parser.add_argument("-c","--color", dest='mycolor', type=str, default="black", help="Color used for plotting")
        elif arg == 'splice':
            parser.add_argument("-s","--splice", dest='sv',action='store', type=int, default=20, help="Divide data in multiple plots, use -s residues per plot")
        else:
            raise NameError

    return parser

def get_font_list(str=True):

    flist = matplotlib.font_manager.get_fontconfig_fonts()
    names = [ matplotlib.font_manager.FontProperties(fname=fname).get_name() for fname in flist ]
    if not str:
        return names
    return textwrap.fill(", ".join(sorted(list(set(names)))), width=69)

def set_default_font(font):
    available_fonts = get_font_list()
    if font not in available_fonts:
        raise NameError

    matplotlib.rcParams['font.family'] = 'sans-serif'
    matplotlib.rcParams['font.sans-serif'] = [ font ]

def parse_label_file(csv_fname, fnames, default_labels):
    if sys.version_info[0] <= 2:
        read_format = 'rb'
    else:
        read_format = 'r'

    label_dict = {}
    labels = list(default_labels)

    try:
        with open(csv_fname, read_format) as csvfile:
            csv_reader = csv.reader(csvfile, delimiter=',', quotechar='|')
            for row in csv_reader:
                if row[0] == 'Residue_name':
                    continue
                if row[1] != '':
                    label_dict[row[0]] = row[1]
    except IOError:
        log.error("Labels file couldn't be read")
        raise IOError
    except:
        log.error("Labels file couldn't be parsed correctly")
        raise

    for i, fname in enumerate(fnames):
        try:
            labels[i] = label_dict[fname]
        except KeyError:
            log.warning("label for residue %s not found; it will be skipped" % fname)

    return labels

def parse_ddg_file(fname, reslist=None, full=False):
    """
    Parser function for free energy file produced by MutateX
    Parameters
    ----------
    fname : str
        name of the file to be read
    reslist : iterable of str or None
        list of the expected mutation residue types. It's used to check that
        the data in the file has the correct size. If None the check will be skipped.
    full : bool
        if True, returns all the fields in the file, otherwise just the averages
        column
    Returns
    -------
    parser : arguments.ArgumentParser instance or any object with the ``add_argument`` method
        the same object of the parameter, modified with additional arguments
    """
    try:
        ddgs = np.loadtxt(fname, comments='#').T
    except:
        log.error("Couldn't open energy file %s or file in the wrong format" % fname)
        raise IOError

    if len(ddgs.shape) == 1:
        ddgs = np.expand_dims(ddgs, 1)

    if reslist is not None:
        if ddgs.shape[1] != len(reslist):
            log.error("file %s has %d values, with %d required." % (fname, len(ddgs), len(reslist)))
            raise TypeError

    if full:
        return ddgs
    return ddgs[0]

def parse_poslist_file(fname,unique_residues):
    """
    Parser function for position list files
    Parameters
    ----------
    fname : str
        name of the file to be read
    Returns
    -------
    restypes : list of str
        list of MutateX residue identifiers
    """

    out = []
    re_position = '(([A-Z]?[A-Z][0-9]+)_?)+'
    matcher = re.compile(re_position)

    try:
        fh = open(fname, 'r')
    except IOError:
        log.error("Couldn't open position list file %s" % fname)
        raise IOError
    for line in fh:
        if matcher.fullmatch(line.strip()) is None:
            log.error("the position list file is not in the right format")
            log.error("format error at %s" % line.strip())
            raise TypeError
        residue=tuple(line.strip().split("_"))

        numbers = [ re.sub("[^0-9]", "", x) for x in residue ]

        if len(set([len(x) for x in residue])) != 1 or\
        len(set(residue)) != len(residue) or\
        len(set(numbers)) != 1:
            log.error("the position list file is not in the right format")
            log.error("format error at %s" % line.strip())
            raise TypeError
        if residue not in unique_residues:
            pdb_residues_list=[]
            for i in unique_residues:
                pdb_residues_list.append(set(residue).issubset(set(i)))
            if pdb_residues_list.count(True) != 1:
                log.error( "%s residue is not written in the right format or it is not contained in pdbfile" % line.strip())
                raise TypeError

        out.append(tuple(sorted([s if str.isdigit(s[1]) else s[1:] for s in residue])))

    return list(set(out))

def filter_reslist(reslist, ref):
    """
    Filters MutateX residue list so that only the residues matching the
    reference list are kept
    Parameters
    ----------
    reslist : list of tuples
        list of residues in MutateX residue specification format
        This is the list to be filtered
    ref : list of tuples
        list of residues. The format of these should be the one
        produced by parse_poslist_file (i.e. similar to the standard
        residue specification, just without the residue type as first
        letter)

    Returns
    -------
    filtered_reslist : list of str
        filtered list of residues in MutateX residue specification format
    """

    filtered_reslist = []

    edited_reslist = [ set([ x[1:] for x in r ]) for r in reslist ]

    for p in ref:
        added = False
        for i,u in enumerate(reslist):
            if set(p).issubset(edited_reslist[i]):
                if not u in filtered_reslist:
                    filtered_reslist.append(u)
                added = True
                break
        if not added:
            pos_str = '_'.join(p)
            log.error("Position %s was not identified in the input PDB files. Exiting..." % pos_str)
            raise TypeError

    return sorted(filtered_reslist, key=lambda x: (x[0][1], int(x[0][2:])))

def parse_mutlist_file(fname):
    """
    Parser function for mutation list files
    Parameters
    ----------
    fname : str
        name of the file to be read
    Returns
    -------
    restypes : list of str
        list of single-letter residue types
    """

    try:
        fh = open(fname, 'r')
    except IOError:
        log.error("Couldn't open mutation list file %s" % fname)
        raise IOError

    restypes = []

    for line in fh:
        if line and not line.startswith("#"):
            str_line = line.strip()
            if len(str_line) == 0:
                continue
            if len(str_line) > 1:
                log.warning("more than one character per line found in mutation list file; only the first letter will be considered")
            mtype = line.strip()[0]
            if mtype not in PDB.Polypeptide.d1_to_index.keys():
                log.error("one or more residue types in the mutation list were incorrectly specified")
                raise TypeError
            restypes.append(mtype)

    fh.close()

    if len(set(restypes)) != len(restypes):
        log.error("mutation list file contains duplicates")
        raise TypeError

    if len(restypes) == 0:
        log.error("No residue types found in mutation list")

    return restypes

def get_residue_list(infile, multimers=True, get_structure=False):
    """
    Reads a PDB file and returns a list of residus (number, type and chain)
    according to the MutateX naming convention
    ----------
    fname : str
        name of the PDB file to be read
    multimers : bool
        whether to automatically detect multimers in the input structure or
        consider each residue independently
    get_structure : bool
        if True, return the ``Bio.PDB.Structure.Structure`` object of the
        input PDB file as well

    Returns
    -------
    residue_list : list of tuples
        list of residues according to the MutateX convention
    structure: instance of ``Bio.PDB.Structure.Structure``
        object corresponding to the loaded PDB structure.

    """

    parser = PDB.PDBParser()

    try:
        structure = parser.get_structure("structure", infile)
    except IOError:
        log.error("couldn't read or parse your PDB file")
        raise IOError

    models = list(structure.get_models())

    if len(models) > 1:
        log.warning("%d models are present in the input PDB file; only the first will be used." % len(models))
    if len(models) < 1:
        log.error("the input PDB file does not contain any model. Exiting ...")
        raise IOError

    model = models[0]

    residue_list = []
    sequences = {}

    for chain in model:
        chain_name = chain.get_id()
        sequences[chain_name] = ''
        for residue in chain:
            try:
                res_code = PDB.Polypeptide.three_to_one(residue.get_resname())
            except:
                log.warning("Residue %s couldn't be recognized; it will be skipped" % residue )
                continue
            if not multimers:
                residue_list.append(("%s%s%d") % (res_code, chain.get_id(), residue.get_id()[1]))
            else:
                sequences[chain_name] += res_code

    if multimers:
        collated_chains = []
        seq_ids, seqs = list(zip(*list(iteritems(sequences))))
        seq_ids = np.array(seq_ids)
        unique_seqs, unique_idxs = np.unique(seqs, return_inverse=True)

        for i in np.unique(unique_idxs):
            collated_chains.append(seq_ids[unique_idxs == i])

        for cg in collated_chains:
            for model in structure:
                for residue in model[cg[0]]:
                    resid = residue.get_id()[1]
                    try:
                        res_code = PDB.Polypeptide.three_to_one(residue.get_resname())
                    except:
                        log.warning("Residue %s couldn't be recognized; it will be skipped" % residue)
                        continue
                    this_res = tuple(sorted([ "%s%s%d" % (res_code, c, resid) for c in cg ], key=lambda x: x[1]))
                    residue_list.append(this_res)

    if get_structure:
        return residue_list, structure

    return residue_list

########################################
# Helper functions for the main script #
########################################


def get_foldx_sequence(pdb, multimers=True):
    """
    Reads a PDB file and returns a list of residus (number, type and chain)
    according to the MutateX naming convention
    Parameters
    ----------
    fname : str
        name of the file to be read
    multimers : bool
        whether to use the multimers mode or not
    Returns
    -------
    restypes : list of str
        list of single-letter residue types
    """
    parser = PDB.PDBParser()
    try:
        structure = parser.get_structure("structure", pdb)
    except:
        log.error("couldn't read or parse your PDB file")
        raise IOError

    residue_list = []
    sequences = {}
    for model in structure:
        for chain in model:
            chain_name = chain.get_id()
            sequences[chain_name] = ''
            for residue in chain:
                try:
                    res_code = PDB.Polypeptide.three_to_one(residue.get_resname())
                except:
                    log.warning("Residue %s in file %s couldn't be recognized; it will be skipped" %(residue, pdb))
                    continue
                if not multimers:
                    residue_list.append(tuple(["%s%s%d" % (res_code, chain.get_id(), residue.get_id()[1])]))
                else:
                    sequences[chain_name] += res_code

    if multimers:
        collated_chains = []
        seq_ids, seqs = list(zip(*list(iteritems(sequences))))
        seq_ids = np.array(seq_ids)
        unique_seqs, unique_idxs = np.unique(seqs, return_inverse=True)

        for i in np.unique(unique_idxs):
            collated_chains.append(seq_ids[unique_idxs == i])

        for cg in collated_chains:
            for model in structure:
                for residue in model[cg[0]]:
                    resid = residue.get_id()[1]
                    try:
                        res_code = PDB.Polypeptide.three_to_one(residue.get_resname())
                    except:
                        log.warning("Residue %s in file %s couldn't be recognized; it will be skipped" %(residue, pdb))
                        continue
                    this_res = tuple(sorted([ "%s%s%d" % (res_code, c, resid) for c in cg ], key=lambda x: x[1]))
                    residue_list.append(this_res)

    return tuple(residue_list)

def safe_makedirs(dirname):
    """
    Safely creates directories and handle corner cases.
    Parameters
    ----------
    dirname : str
        name of the directory to be created
    """
    if os.path.exists(dirname):
        if not os.path.isdir(dirname):
            log.error("%s exists but is not a directory." % dirname)
            raise IOError
        else:
            log.warning("directory %s already exists" % dirname)
            return
    else:
        try:
            os.makedirs(dirname)
        except:
            log.error("Could not create directory %s." % dirname )
            raise IOError

def safe_cp(source, destination, dolink=True):
    """
    Safely copies or links files and handles corner cases.
    Parameters
    ----------
    source : str
        source file name for copy
    destination : str
        destionation file name for copy
    dolink : bool
        make symbolic links instead of copying
    """
    if os.path.abspath(source) == os.path.abspath(destination):
        return

    if dolink:
        verb = "link"
    else:
        verb = "copy"

    if not os.path.exists(source):
        log.error("Couldn't %s file %s; no such file or directory" % (verb, source))
        raise IOError

    if not os.path.isfile(source):
        log.error("Couldn't %s file %s; it is not a file" % (verb, source))
        raise IOError

    if not dolink:
        if os.path.exists(destination):
            log.warning("Destination file %s already exists; it will be overwritten." % destination)
        try:
            shutil.copyfile(source, destination)
        except:
            log.error("Couldn't copy file %s to %s" % (source, destination))
            raise IOError
    else:
        if os.path.exists(destination):
            log.error("Destination file %s already exists; it will not be overwritten by a link" % destination)
            raise IOError
        else:
            try:
                os.symlink(source, destination)
            except:
                log.error("Couldn't link file %s to %s" % (source, destination))
                raise IOError

def load_structures(pdb, check_models=False):
    """
    Loads structure object from PDB file and handles common failures
    Parameters
    ----------
    pdb : str
        PDB file name
    check_models : bool
        perform basic checks on the loaded models and fix problems if possible.
        Currently it just checks whether the chain identifier is assigned
        and assign one if not
    Returns
    ----------
    structure : ``PDB.Structure`` object
        structure loaded from the PDB file

    """

    parser = PDB.PDBParser()

    try:
        structure = parser.get_structure("structure", pdb)
    except:
        log.error("couldn't read or parse your PDB file")
        raise IOError

    if len(structure.get_list()) == 0:
        log.error("File %s doesn't contain any useful model." % pdb)
        raise IOError

    if check_models:
        log.info("checking models in pdb file")
        for model in structure:
            for chain in model:
                if chain.id == ' ':
                    log.warning('at least one residue in model %d in pdb file has no chain identifier. Will be defaulted to A.' % model.id)
                    chain.id = 'A'

    return structure

def load_runfile(runfile):
    """
    Parses runfile template and handles most common problems
    Parameters
    ----------
    runfile : str
        Input run file name
    Returns
    ----------
    data : str
        content of the runfile

    """

    try:
        with open(runfile, 'r') as fh:
            data = fh.read()
    except:
        log.error("Couldn't open runfile %s." % runfile)
        raise IOError

    return data

def foldx_worker(run):
    """
    FoldX parallel worker - starts FoldX run and logs event
    Parameters
    ----------
    run : ``mutatex.FoldXRun`` instance
        FoldX run to be performed
    Returns
    ----------
    run_name : str
        name of the run
    run_result : bool
        whether the run has been performed (True) or not (False)
    """


    log.info("starting FoldX run %s" % run.name)
    return (run.name, run.run())

def parallel_foldx_run(foldx_runs, np):
    """
    FoldX parallel run - run different foldx runs in parallel
    Parameters
    ----------
    foldx_runs : iterable of ``mutatex.FoldXRun`` instances
        FoldX runs to be performed
    np : int
        number of runs to be performed at the same time
    Returns
    ----------
    results : list of (str, bool) tuples
        whether each run has been complete successfully (name and status)
    """
    pool = ThreadPool(np)

    result = pool.imap_unordered(foldx_worker, foldx_runs)

    pool.close()
    pool.join()

    return list(result)


def split_pdb(filename, structure, checked, workdir):
    """
    split models in a ``PDB.Structure`` object into a file each, which
    is written to disk.
    Parameters
    ----------
    filename : file name of the original PDB file. It will be used to derive
        the file names of the single model files
    structure : instance of ``PDB.Structure``
        structure object from which models will be extracted
    checked : bool
        whether append "_checked" to the filename
    workdir : str
        directory where the file will be saved
    Returns
    ----------
    pdb_list : list of (str)
        list of file names of the files that have been written
    """

    pdb_list = []

    writer = PDB.PDBIO()
    parser = PDB.PDBParser()

    for model in structure:
        tmpstruc = PDB.Structure.Structure('structure')
        tmpstruc.add(model)
        writer.set_structure(tmpstruc)
        if checked:
            checked_str = "_checked"
        else:
            checked_str = ""
        writer.save(os.path.join(workdir, "%s_model%d%s.pdb" % (os.path.splitext(os.path.basename(filename))[0], model.id, checked_str)))
        pdb_list.append("%s_model%d%s.pdb" % (os.path.splitext(os.path.basename(filename))[0], model.id, checked_str))

    return pdb_list

def save_energy_file(fname, data, fmt="%.5f", do_avg=True, do_std=False, do_min=False, do_max=False, axis=1):
    """
    saves mutation energy data to file in the Mutatex format
    Parameters
    ----------
    fname : str
        file name the data will be written to
    fmt : str
        output file format specification - see ``numpy.savetxt`` fmt option
    data : ``numpy.array``
        data to be written in the file
    do_avg : bool
        write column of average values
    do_std : bool
        write column of standard deviation values
    do_min : bool
        write column of minimum values
    do_max : bool
        write column of maximum values
    axis : int
        axis on which average/standard deviation/minimum/maximum will be calculated
    """

    out = []
    header_cols = []

    if do_avg:
        out.append(np.average(data, axis=axis))
        header_cols.append("avg")
    if do_std:
        out.append(np.std(data, axis=axis))
        header_cols.append("std")
    if do_min:
        out.append(np.min(data, axis=axis))
        header_cols.append("min")
    if do_max:
        out.append(np.max(data, axis=axis))
        header_cols.append("max")

    header = "\t".join(header_cols)

    out = np.array(out).T

    try:
        np.savetxt(fname, out, fmt=fmt, header=header)
    except:
        log.error("Couldn't write energy file %s" % fname)
        raise IOError

def save_interaction_energy_file(fname, data, fmt="%.5f", do_avg=True, do_std=False, do_min=False, do_max=False, axis=1):
    """
    saves interaction energy data to file in the Mutatex format
    Parameters
    ----------
    fname : str
        file name the data will be written to
    fmt : str
        output file format specification - see ``numpy.savetxt`` fmt option
    data : ``numpy.array``
        data to be written in the file
    do_avg : bool
        write column of average values
    do_std : bool
        write column of standard deviation values
    do_min : bool
        write column of minimum values
    do_max : bool
        write column of maximum values
    axis : int
        axis on which average/standard deviation/minimum/maximum will be calculated
    """

    out = []
    header_cols = []

    if do_avg:
        out.append(np.average(data, axis=axis))
        header_cols.append("avg")
    if do_std:
        out.append(np.std(data, axis=axis))
        header_cols.append("std")
    if do_min:
        out.append(np.min(data, axis=axis))
        header_cols.append("min")
    if do_max:
        out.append(np.max(data, axis=axis))
        header_cols.append("max")

    header = "\t".join(header_cols)

    out = np.array(out).T

    try:
        np.savetxt(fname, out, fmt=fmt, header=header)
    except:
        log.error("Couldn't interaction energy write file %s" % fname)
        raise IOError

def compress_mutations_dir(cwd, mutations_dirname, mutations_archive_fname='mutations.tar.gz'):
    """
    compresses directory in a tarball file. Designed to compress the "mutations"
    directory but works with any.
    Parameters
    ----------
    cwd : str
        current working directory
    mutations_dirname : str
        name of the "mutations directory"
    mutations_archive_fname : str
        name fo the archive file to be written
    """

    archive_path = os.path.join(cwd, mutations_archive_fname)
    mutations_dir_path = mutations_dirname

    log.info("Compressing mutations directory as per user request")
    if not os.path.isdir(cwd):
        log.warning("Directory mutations doesn't exist; it won't be compressed.")

    try:
        fh = tar.open(archive_path, 'w:gz')
    except:
        log.warning("Couldn't open compressed file %s for writing." % mutations_archive_fname)
        return

    try:
        fh.add(mutations_dir_path)
    except:
        log.warning("Couldn't build compressed archive. This step will be skipped.")
        fh.close()
        os.remove(archive_path)
        return

    fh.close()
    log.info("Removing mutations directory ...")
    shutil.rmtree(mutations_dir_path)
    return

def kill_subprocess(pid):
    """
    kills a subprocess manually in case of disorderly exit
    Parameters
    ----------
    pid : int or None
        process ID or None
    """

    if pid is not None:
        try:
            os.kill(pid, signal.SIGKILL)
            log.info("terminating FoldX subprocess %d" % pid)
        except ProcessLookupError:
            pass

def termination_handler(signalnum, handler):
    """
    handle SIGTERM and SIGINT intelligently and exits. Calling exit() allows to
    kill all the processes registered in atexit, which are all the foldx runs
    currently undergoing
    Parameters
    ----------
    signalnum : int
        signal number
    handler : instance of frame
        frame object
    """

    log.info("Received termination signal - mutatex will be stopped")
    log.shutdown()
    sys.exit(-1)

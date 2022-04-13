import os
import sys
import json
from pathlib import Path
from functools import wraps

import numpy as np
import h5py as h5

from classynet import training
from classynet.plotting import plotter
from classynet.generate import generator
from classynet.testing import tester
from classynet.testing.benchmark import BenchmarkRunner
from classynet.plotting.benchmark_plotter import BenchmarkPlotter
from classynet.models import ALL_NETWORK_STRINGS

from classynet.tools.parameter_sampling import EllipsoidDomain

def create_dir(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        path = func(*args, **kwargs)
        path.mkdir(parents=True, exist_ok=True)
        return path
    return wrapper

class ResultDir:

    def __init__(self, root):
        self.root = root

    def sub(self, subdir):
        subdir = self.root / subdir
        subdir.mkdir(exist_ok=True)
        return ResultDir(subdir)

    @property
    @create_dir
    def plots(self):
        return self.root / "plots"

    @property
    def stats_file(self):
        return self.root / "errors.pickle"

class Workspace:
    """
    Represents the workspace (corresponding to a directory on disk) in which
    training/validation data, models, logs, plots, etc. will be stored.
    This class wraps around a directory and endows it with some utility methods.
    """

    def __init__(self, path, results=None):
        self.path = Path(path)
        self.path.mkdir(parents=True, exist_ok=True)

        if results is not None:
            self._results = results
        else:
            result_dir = self.path / "results"
            result_dir.mkdir(exist_ok=True)
            self._results = ResultDir(result_dir)

    def sub(self, sub):
        return Workspace(self.path, results=self._results.sub(sub))

    @property
    def plots(self):
        return self._results.plots

    @property
    def stats_file(self):
        return self._results.stats_file

    @property
    @create_dir
    def training_data(self):
        return self.path / "training"

    @property
    @create_dir
    def validation_data(self):
        return self.path / "validation"

    @property
    @create_dir
    def test_data(self):
        return self.path / "test"

    @property
    @create_dir
    def models(self):
        return self.path / "models"

    def path(self):
        return self.path

    def model_path(self, name):
        return self.models / f"{name}.pt"

    def model_path_checkpoint(self, name, checkpoint):
        return self.models / f"{name}_checkpoint_{checkpoint}.pt"

    @property
    @create_dir
    def data(self):
        """
        path to standard k array
        """
        return self.path / "data"

    @property
    @create_dir
    def benchmark(self):
        """
        path to directory where benchmark results are saved
        """
        return self.plots / "benchmark"

    @property
    def benchmark_data(self):
        """
        path to data file inside benchmark directory
        """
        return self.benchmark / "data.json"

    @property
    def normalization_file(self):
        return self.training_data / "normalization.json"

    @property
    def manifest(self):
        return self.path / "manifest.json"

    @property
    def k(self):
        """
        path to standard k array
        """
        return self.data / "k.npy"

    @property
    @create_dir
    def history(self):
        return self.path / "history"

    def history_for(self, name):
        return self.history / f"{name}.csv"

    @property
    def domain_descriptor(self):
        return self.data / "domain.json"

    def domain(self):
        return EllipsoidDomain.load(self,self.domain_descriptor)

    def domain_from_path(self,
        pnames,
        bestfit_path        = None,
        covmat_path         = None,
        sigma_train         = 6,
        sigma_validation    = 5,
        sigma_test          = 5,
        ):
        # If bestfit and covmat paths are given they are loaded. 
        # If there are no paths given bestfit and covmat are searched in the workspace.data directory
        if bestfit_path==None:
            bestfit_file = [_ for _ in os.listdir(self.data) if _[-7:]=='bestfit']
            if (len(bestfit_file)!=1): raise ValueError('more then one bestfit was found. Specify!') 
            bestfit_path = self.data / bestfit_file[0]
        if covmat_path==None:
            covmat_file = [_ for _ in os.listdir(self.data) if _[-6:]=='covmat']
            if (len(covmat_file)!=1): raise ValueError('more then one covmat was found. Specify!') 
            covmat_path = self.data / covmat_file[0]

        return EllipsoidDomain.from_paths(
            self,
            pnames,
            bestfit_path, 
            covmat_path, 
            sigma_train = sigma_train, 
            sigma_validation = sigma_validation,
            sigma_test = sigma_test,
        )

    def generator(self):
        return generator.Generator(self)

    def loader(self):
        return Loader(self)

    def trainer(self):
        return training.Trainer(self)

    def tester(self):
        return tester.Tester(self)

    def plotter(self):
        return plotter.Plotter(self)

    def benchmark_runner(self, *args, **kwargs):
        return BenchmarkRunner(self, *args, **kwargs)

    def benchmark_plotter(self):
        return BenchmarkPlotter(self)

    def network_names(self):
        return ALL_NETWORK_STRINGS


class GenerationalWorkspace(Workspace):

    def __init__(self, path, generations, results=None):
        '''
        generations: network dict with numbers
        '''
        super().__init__(path, results=results)
        self.generations = generations

        if results is not None:
            self._results = results
        else:
            result_dir = self.path / "results"
            result_dir.mkdir(exist_ok=True)
            g = self.generations
            suffix = "_".join("{}_{}".format(k, g[k]) for k in sorted(self.generations))
            path = self.path / ("results_" + suffix)
            path.mkdir(exist_ok=True)
            self._results = ResultDir(path)

    def sub(self, sub):
        return GenerationalWorkspace(
            path=self.path,
            generations=self.generations,
            results=self._results.sub(sub))

    def model_path(self, name):
        if name in self.generations:
            return self.models / "{}_{}.pt".format(name, self.generations[name])
        else:
            return self.models / "{}.pt".format(name)

    def model_path_checkpoint(self, name, checkpoint):
        return self.models / "{}_{}_checkpoint_{}.pt".format(
            name, self.generations[name], checkpoint
        )

    def history_for(self, name):
        return self.history / f"{name}_{self.generations[name]}.csv"


class Loader:
    def __init__(self, workspace):
        self.workspace = workspace

    def manifest(self):
        with open(self.workspace.manifest) as src:
            return json.load(src)

    def k(self):
        return np.load(self.workspace.k)

    def cosmological_parameters(self, file_name = 'parameters'):
        def load(my_set):
            my_path = self.workspace.path / my_set / '{}.h5'.format(file_name)
            if os.path.isfile(my_path):
                with h5.File(my_path, "r") as f:
                    return {key: list(f[my_set].get(key)) for key in f[my_set].keys()}
            else:
                return None

        training_parameter = load('training')
        validation_parameter = load('validation')
        test_parameter = load('test')

        return(training_parameter, validation_parameter, test_parameter)


    def domain_descriptor(self):
        path = self.workspace.domain_descriptor
        # TODO hardcode EllipsoidDomain here?
        return EllipsoidDomain.load(self.workspace, path)

    # def domain_descriptor(self):
    #     path = self.workspace.domain_descriptor()
    #     with open(path) as f:
    #         d = json.load(f)
    #     d["bestfit"] = np.array(d["bestfit"])
    #     d["covmat"] = np.array(d["covmat"])
    #     return d

    def stats(self):
        """
        Load training stats.
        Requires that stats have already been generated by `Tester.test()`.
        """
        import pickle
        # TODO prefix?
        path = self.workspace.stats_file
        print("Loading stats from", path)
        with open(path, "rb") as f:
            return pickle.load(f)

    def benchmark_data(self):
        with open(self.workspace.benchmark_data) as f:
            return json.load(f)

from numpy import *
from scipy.special import erfinv, gammaln
from scipy.stats import skewnorm, norm, truncnorm
import matplotlib.pyplot as plt

import pymultinest
import mpi4py

import json
import time

# Read in data
bkgpdf_data = genfromtxt("Data/bkgpdf.txt")
brnpdf_data = genfromtxt("Data/brnpdf.txt")
brndelayedpdf_data = genfromtxt("Data/delbrnpdf.txt")
cevnspdf_data = genfromtxt("Data/cevnspdf.txt")
obs_data = genfromtxt("Data/datanobkgsub.txt")

# Read in systematics PDFs
brnpdf_m1sigTiming = genfromtxt("Data/SystErrors/brnpdf-1sigBRNTimingMean.txt")[:,3]
brnpdf_p1sigTiming = genfromtxt("Data/SystErrors/brnpdf+1sigBRNTimingMean.txt")[:,3]
brnpdf_m1sigEnergy = genfromtxt("Data/SystErrors/brnpdf-1sigEnergy.txt")[:,3]
brnpdf_p1sigEnergy = genfromtxt("Data/SystErrors/brnpdf+1sigEnergy.txt")[:,3]
cevnspdf_m1sigF90 = genfromtxt("Data/SystErrors/cevnspdf-1sigF90.txt")[:,3]
cevnspdf_p1sigF90 = genfromtxt("Data/SystErrors/cevnspdf+1sigF90.txt")[:,3]
cevnspdfCEvNSTiming = genfromtxt("Data/SystErrors/cevnspdfCEvNSTimingMeanSyst.txt")[:,3]
brnpdfBRNTimingWidth = genfromtxt("Data/SystErrors/brnpdfBRNTimingWidthSyst.txt")[:,3]

# Set up CEvNS, BRN, and Observed arrays
brn_prompt = brnpdf_data[:,3]
brn_delayed = brndelayedpdf_data[:,3]
obs = obs_data[:,3]
cevns = cevnspdf_data[:,3]
ss = bkgpdf_data[:,3]

# Flat bins
entries = obs_data.shape[0]
keVee = obs_data[:,0]
f90 = obs_data[:,1]
timing = obs_data[:,2]

# Define a boolean array for any cuts.
timing_cut = timing < 12
keVee_lo_cut = keVee > 0
keVee_hi_cut = keVee < 140
f90_cut = f90 < 1.0

cut_crit = timing_cut*keVee_lo_cut*keVee_hi_cut*f90_cut

# Define stats CDFs for priors
ss_error = sqrt(sum(ss)/5)/sum(ss) # percent error
normSS = norm(scale=ss_error) #truncnorm(-1.0,1.0,scale=ss_error)
normPromptBRN = norm(scale=0.3) #truncnorm(-1.0,1.0,scale=0.3)
normDelayedBRN = norm(scale=1.0) #truncnorm(-1.0,1.0,scale=1.0)




# Define Priors for MultiNest
def prior_stat(cube, n, d):
    cube[0] = 2*cube[0]  # CEvNS norm
    cube[1] = normSS.ppf(cube[1])  # SS norm
    cube[2] = normPromptBRN.ppf(cube[2])  # BRN prompt norm
    cube[3] = normDelayedBRN.ppf(cube[3])  # BRN delayed norm

def prior_stat_null(cube, n, d):
    cube[0] = normSS.ppf(cube[0])  # SS norm
    cube[1] = normPromptBRN.ppf(cube[1])  # BRN prompt norm
    cube[2] = normDelayedBRN.ppf(cube[2])  # BRN delayed norm 




# Generate new PDFs with nuisance-controlled norms
def events_gen_stat(cube):
    brn_syst = (1+cube[2])*brn_prompt + (1+cube[3])*brn_delayed
    cevns_syst = cube[0]*cevns
    ss_syst = (1+cube[1])*ss

    return (brn_syst + cevns_syst + ss_syst).clip(min=0.0)

# Generate new PDFs with nuisance-controlled norms (no CEvNS)
def events_gen_stat_null(cube):
    brn_syst = (1+cube[1])*brn_prompt + (1+cube[2])*brn_delayed
    ss_syst = (1+cube[0])*ss

    return (brn_syst + ss_syst).clip(min=0.0)




def poisson(obs, theory):
    ll = 0.
    for i in range(entries):
        if cut_crit[i]:
            ll += obs[i] * log(theory[i]) - theory[i] - gammaln(obs[i]+1)
    return ll

# TODO(AT): parse the MLE parameters directly from MultiNest output files
def PrintSignificance():
    # Print out totals.
    print("TOTALS:")
    print("N_obs = ", sum(obs[cut_crit]))
    print("N_ss = ", sum(ss[cut_crit]))
    print("N_brn =", sum(brn_prompt[cut_crit] + brn_delayed[cut_crit]))
    print("N_cevns = ", sum(cevns[cut_crit]))

    # Save best-fit (MLE) parameters from MultiNest (in <out>stats.dat)
    # Truncated gaussian
    bf_stat = [0.128203949389575733E+01,
              -0.757751720547599188E-02,
               0.928830540200280969E-01,
              -0.681121212215910043E+00]
    bf_stat_null = [-0.799580130637969101E-02,
                     0.253213583049654078E+00,
                    -0.514351228113789194E+00]
    # Unconstrained Gaussian
    bf_stat = [0.168960153287222759E+01,
              -0.312937517992761469E-01,
               0.780942325684447630E-01,
              -0.970385882467374672E+00]
    bf_stat_null = [-0.147905160635425168E-01,
                     0.245574237324468231E+00,
                    -0.460897530294036739E+00]

    # Get ratio test
    print("Significance (stat):")
    stat_q = sqrt(abs(2*(-poisson(obs, events_gen_stat(bf_stat)) \
                        + poisson(obs, events_gen_stat_null(bf_stat_null)))))
    print(stat_q)




def RunMultinest():
    def loglike(cube, ndim, nparams):
        n_signal = events_gen_stat(cube)
        ll = 0.0
        for i in range(entries):
            if cut_crit[i]:
                ll += obs[i] * log(n_signal[i]) - n_signal[i] - gammaln(obs[i]+1)
        return sum(ll)

    save_str = "cenns10_stat_t"
    out_str = "multinest/" + save_str + "/" + save_str
    json_str = "multinest/" + save_str + "/params.json"

    # Run the sampler with CEvNS, BRN, and SS.
    pymultinest.run(loglike, prior_stat, 4,
                    outputfiles_basename=out_str,
                    resume=False, verbose=True, n_live_points=1000, evidence_tolerance=0.5,
                    sampling_efficiency=0.8)

    # Save the parameter names to a JSON file.
    params_stat = ["cevns_norm", "ss_norm", "BRN_prompt_norm", "BRN_delayed_norm"]
    json.dump(params_stat, open(json_str, 'w'))




def RunMultinestNull():
    def loglike(cube, ndim, nparams):
        n_signal = events_gen_stat_null(cube)
        ll = 0.0
        for i in range(entries):
            if cut_crit[i]:
                ll += obs[i] * log(n_signal[i]) - n_signal[i] - gammaln(obs[i]+1)
        return sum(ll)

    save_str = "cenns10_stat_no_cevns_t"
    out_str = "multinest/" + save_str + "/" + save_str
    json_str = "multinest/" + save_str + "/params.json"

    # Run the sampler with just BRN, and SS.
    pymultinest.run(loglike, prior_stat_null, 3,
                    outputfiles_basename=out_str,
                    resume=False, verbose=True, n_live_points=1000, evidence_tolerance=0.5,
                    sampling_efficiency=0.8)

    # Save the parameter names to a JSON file.
    params_stat_null = ["ss_norm", "BRN_prompt_norm", "BRN_delayed_norm"]
    json.dump(params_stat_null, open(json_str, 'w'))




if __name__ == '__main__':

    print("Running MultiNest with CEvNS, BRN, and SS components...")

    RunMultinest()

    print("Starting next run for only BRN and SS components (5s)...")

    time.sleep(5.0)

    RunMultinestNull()

    #PrintSignificance()


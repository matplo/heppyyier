"""
Experiment: pip-cppyy (pythia8, fastjet) + ROOT TTree in the same session.

Load order: cppyy packages first, then import ROOT.
ROOT is used only for TFile/TTree output; generation and clustering
stay entirely in pip-cppyy land — no object passing across cling contexts.

Run:
    module load fastjet pythia8 root   # or rely on heppyyier.load() below
    python demo_pythia_fastjet_root_cppyy.py
"""

import heppyyier
heppyyier.load("pythia8")
heppyyier.load("fastjet")
heppyyier.load("root")    # adds ROOT lib/ to sys.path; pip-cppyy already owns cling

import ctypes, pathlib
import cppyy
import pythia8
import fastjet

# ROOT's _facade._finalSetup() calls cppyy.gbl.ROOT.GetROOT() — but at this
# point cppyy is pip-cppyy, which only knows pythia8/fastjet headers.
# Fix: pre-load ROOT's core libraries and headers into pip-cppyy's cling so
# that cppyy.gbl.ROOT, cppyy.gbl.TFile, cppyy.gbl.TTree are all available
# before import ROOT triggers _finalSetup.
_root_lib = pathlib.Path(heppyyier.get_registry().get('root')['lib_dir'])
_root_inc = pathlib.Path(heppyyier.get_registry().get('root')['include_dir'])
cppyy.add_include_path(str(_root_inc))
for _lib in ['libCore', 'libImt', 'libNet', 'libRIO', 'libHist', 'libTree']:
    for _ext in ('.dylib', '.so'):
        _candidate = _root_lib / f"{_lib}{_ext}"
        if _candidate.exists():
            try:
                ctypes.CDLL(str(_candidate), ctypes.RTLD_GLOBAL)
            except OSError as e:
                print(f"[pre-load] warning: {_lib}: {e}")
            break
for _header in ('TROOT.h', 'TFile.h', 'TTree.h'):
    cppyy.include(_header)

import ROOT   # _finalSetup now finds cppyy.gbl.ROOT via pip-cppyy's cling

PseudoJetVec = cppyy.gbl.std.vector[fastjet.PseudoJet]

# ---------------------------------------------------------------------------
# ROOT output: TFile + TTree with scalar branches per jet
# ---------------------------------------------------------------------------
outfile = ROOT.TFile("pythia_jets_cppyy.root", "RECREATE")
tree    = ROOT.TTree("jets", "anti-kt R=0.4 jets from Pythia8 pp dijets")

import array
b_event      = array.array('i', [0])
b_pt         = array.array('f', [0.])
b_eta        = array.array('f', [0.])
b_phi        = array.array('f', [0.])
b_e          = array.array('f', [0.])
b_m          = array.array('f', [0.])
b_nconst     = array.array('i', [0])
b_is_leading = array.array('i', [0])

tree.Branch("event",      b_event,      "event/I")
tree.Branch("pt",         b_pt,         "pt/F")
tree.Branch("eta",        b_eta,        "eta/F")
tree.Branch("phi",        b_phi,        "phi/F")
tree.Branch("e",          b_e,          "e/F")
tree.Branch("m",          b_m,          "m/F")
tree.Branch("nconst",     b_nconst,     "nconst/I")
tree.Branch("is_leading", b_is_leading, "is_leading/I")

# ---------------------------------------------------------------------------
# Pythia: pp 13 TeV QCD dijets
# ---------------------------------------------------------------------------
pythia = pythia8.Pythia()
pythia.readString("Beams:eCM = 13000.")
pythia.readString("HardQCD:all = on")
pythia.readString("PhaseSpace:pTHatMin = 20.")
pythia.readString("Next:numberShowEvent = 0")
pythia.readString("Print:quiet = on")
pythia.init()

R       = 0.4
pt_min  = 20.0
jet_def = fastjet.JetDefinition(fastjet.antikt_algorithm, R)

# ---------------------------------------------------------------------------
# Event loop
# ---------------------------------------------------------------------------
n_events = 200
print(f"Generating {n_events} events, anti-kt R={R}, pt > {pt_min} GeV")

for i_event in range(n_events):
    if not pythia.next():
        continue

    event     = pythia.event
    particles = PseudoJetVec()
    for i in range(event.size()):
        p = event[i]
        if not p.isFinal() or not p.isVisible():
            continue
        particles.push_back(fastjet.PseudoJet(p.px(), p.py(), p.pz(), p.e()))

    if particles.size() == 0:
        continue

    cs   = fastjet.ClusterSequence(particles, jet_def)
    jets = fastjet.sorted_by_pt(cs.inclusive_jets(pt_min))

    for j, jet in enumerate(jets):
        b_event[0]      = i_event
        b_pt[0]         = jet.pt()
        b_eta[0]        = jet.eta()
        b_phi[0]        = jet.phi()
        b_e[0]          = jet.e()
        b_m[0]          = jet.m()
        b_nconst[0]     = len(cs.constituents(jet))
        b_is_leading[0] = 1 if j == 0 else 0
        tree.Fill()

    if i_event < 3 and jets:
        print(f"  event {i_event}: {int(particles.size())} particles, {len(jets)} jets, leading pt={jets[0].pt():.1f}")

pythia.stat()

n_entries = tree.GetEntries()
outfile.Write()
outfile.Close()

print(f"\nWrote pythia_jets_cppyy.root  ({n_events} events, {n_entries} jet entries)")
print('  root -l pythia_jets_cppyy.root')
print('  jets->Draw("pt>>h(50,0,200)","is_leading==1")')

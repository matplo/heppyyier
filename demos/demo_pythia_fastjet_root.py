"""
Demo: Pythia8 event generation + FastJet anti-kt jets → ROOT ntuple.

Generates pp → QCD dijet events, clusters jets with anti-kt R=0.4, and
writes per-jet and per-event variables into a ROOT TTree saved to a .root file.

Run with:
    module load fastjet pythia8 root   # or heppyyier.load() calls below
    python demo_pythia_fastjet_root.py

Output: pythia_jets.root  (TTree "jets" with per-jet branches)
"""

import heppyyier
heppyyier.load("pythia8")
heppyyier.load("fastjet")
heppyyier.load("root")
import ROOT
heppyyier.gSystem_load("pythia8")   # make Pythia8 symbols available to ROOT's cling
heppyyier.gSystem_load("fastjet")

import cppyy
import pythia8
import fastjet

PseudoJetVec = cppyy.gbl.std.vector[fastjet.PseudoJet]

# ---------------------------------------------------------------------------
# Output ROOT file and TTree
# ---------------------------------------------------------------------------
outfile = ROOT.TFile("pythia_jets.root", "RECREATE")
tree    = ROOT.TTree("jets", "anti-kt R=0.4 jets from Pythia8 pp dijets")

# Per-event branches
b_event_n    = ROOT.std.vector["int"](1);    b_event_n[0]   = 0
b_npart      = ROOT.std.vector["int"](1);    b_npart[0]     = 0
b_njets      = ROOT.std.vector["int"](1);    b_njets[0]     = 0

# Per-jet branches (one entry per jet, event index in b_event_n)
b_pt         = ROOT.std.vector["float"]()
b_eta        = ROOT.std.vector["float"]()
b_phi        = ROOT.std.vector["float"]()
b_e          = ROOT.std.vector["float"]()
b_m          = ROOT.std.vector["float"]()
b_nconst     = ROOT.std.vector["int"]()
b_is_leading = ROOT.std.vector["int"]()

tree.Branch("event",    b_event_n,    "event/I")
tree.Branch("npart",    b_npart,      "npart/I")
tree.Branch("njets",    b_njets,      "njets/I")
tree.Branch("pt",       b_pt)
tree.Branch("eta",      b_eta)
tree.Branch("phi",      b_phi)
tree.Branch("e",        b_e)
tree.Branch("m",        b_m)
tree.Branch("nconst",   b_nconst)
tree.Branch("is_leading", b_is_leading)

# ---------------------------------------------------------------------------
# Pythia setup: pp 13 TeV QCD dijets
# ---------------------------------------------------------------------------
pythia = pythia8.Pythia()
pythia.readString("Beams:eCM = 13000.")
pythia.readString("HardQCD:all = on")
pythia.readString("PhaseSpace:pTHatMin = 20.")
pythia.readString("Next:numberShowEvent = 0")
pythia.readString("Print:quiet = on")
pythia.init()

# ---------------------------------------------------------------------------
# Jet definition: anti-kt R=0.4, pt > 20 GeV
# ---------------------------------------------------------------------------
R      = 0.4
pt_min = 20.0
jet_def = fastjet.JetDefinition(fastjet.antikt_algorithm, R)

# ---------------------------------------------------------------------------
# Event loop
# ---------------------------------------------------------------------------
n_events = 200
print(f"Generating {n_events} Pythia8 pp → dijets events, anti-kt R={R}, pt > {pt_min} GeV")

for i_event in range(n_events):
    if not pythia.next():
        continue

    event = pythia.event

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

    # Clear per-jet vectors for this event
    b_pt.clear();  b_eta.clear(); b_phi.clear()
    b_e.clear();   b_m.clear();   b_nconst.clear(); b_is_leading.clear()

    b_event_n[0] = i_event
    b_npart[0]   = int(particles.size())
    b_njets[0]   = len(jets)

    for j, jet in enumerate(jets):
        b_pt.push_back(jet.pt())
        b_eta.push_back(jet.eta())
        b_phi.push_back(jet.phi())
        b_e.push_back(jet.e())
        b_m.push_back(jet.m())
        b_nconst.push_back(len(cs.constituents(jet)))
        b_is_leading.push_back(1 if j == 0 else 0)

    tree.Fill()

    if i_event < 3:
        print(f"  event {i_event}: {b_npart[0]} particles, {b_njets[0]} jets")
        for j in range(b_njets[0]):
            print(f"    jet {j}: pt={b_pt[j]:.1f}  eta={b_eta[j]:.2f}  phi={b_phi[j]:.2f}  nconst={b_nconst[j]}")

# ---------------------------------------------------------------------------
# Save and report
# ---------------------------------------------------------------------------
pythia.stat()

n_entries = tree.GetEntries()   # read before Close() frees the TTree
outfile.Write()
outfile.Close()

print(f"\nWrote pythia_jets.root  ({n_events} events, {n_entries} tree entries)")
print("Branches: event, npart, njets, pt[], eta[], phi[], e[], m[], nconst[], is_leading[]")
print("\nQuick check with ROOT:")
print("  root -l pythia_jets.root")
print('  jets->Draw("pt>>h(50,0,200)","is_leading==1")')

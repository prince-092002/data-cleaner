# Shim: engine falls back to csv.Sniffer on any exception here.
class Sniffer:
    def sniff(self, sample, delimiters=None):
        raise RuntimeError("clevercsv unavailable in Pyodide")

"""PUBLIC teaching object, not a hidden benchmark or independent physics solver.

Run separately from the inverse API. The recommender receives the resulting CSV,
not these disclosed generating parameters or future samples. Noise seeds are fixed
for repeatable teaching; a replay is not another independent experiment.
"""
import argparse
import csv
import json
import math
from pathlib import Path
import random


def sample(model, positions, followup=False):
    rng = random.Random(734521 + (1009 if followup else 0))
    result = []
    for x in positions:
        if model == 'slit':
            # Fourier focal plane: lambda=633 nm, f=200 mm, a=23 um,
            # d=178 um; independent declared exposure/background per scan.
            q = (x - .08) / (.000633 * 200)
            u = math.pi * .023 * q
            sinc = math.sin(u) / u if u else 1.
            a, b = (.86, .06) if followup else (1., .04)
            value = b + a * sinc ** 2 * math.cos(math.pi * .178 * q) ** 2 + rng.gauss(0, .008)
        elif model == 'gaussian':
            # M^2=1, free propagation, public w0=82 um and z0=35 mm.
            zr = math.pi * .082 ** 2 / .000633
            value = 82 * math.sqrt(1 + ((x - 35) / zr) ** 2) + rng.gauss(0, .5)
        elif model == 'film':
            # Lossless n=2 film, t=273 nm, incident/substrate n=1.
            r = (1 / 3) ** 2
            s = math.sin(2 * math.pi * 2 * 273 / x) ** 2
            value = 4 * r * s / ((1 - r) ** 2 + 4 * r * s) + rng.gauss(0, .001)
            if not 0 <= value <= 1:
                raise ValueError('Teaching reflectance left [0,1]; no clipping or retry')
        else:
            raise ValueError('Unknown model')
        result.append([x, value])
    return result


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--model', choices=['slit', 'gaussian', 'film'], required=True)
    p.add_argument('--out', required=True)
    p.add_argument('--proposal', help='Saved proposal.json; sample only its selected positions')
    args = p.parse_args()
    if args.proposal:
        proposal = json.loads(Path(args.proposal).read_text(encoding='utf-8'))
        if proposal.get('replacement_strategy'):
            positions = proposal['replacement_strategy']['wavelengths_nm' if args.model == 'film' else 'positions_mm']
        else:
            plan = next(v for v in proposal['plans'] if v['id'] == proposal['recommended_id'])
            positions = plan['wavelengths_nm' if args.model == 'film' else 'prediction_x_mm']
    else:
        positions = [633.] if args.model == 'film' else [-.65 + 1.3 * i / 80 for i in range(81)] if args.model == 'slit' else [-40. + 8 * i for i in range(21)]
    headers = {'slit': ['position_mm', 'intensity_relative'],
               'gaussian': ['z_mm', 'radius_1e2_um'],
               'film': ['wavelength_nm', 'reflectance_calibrated']}
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open('x', encoding='utf-8', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(headers[args.model])
        writer.writerows(sample(args.model, positions, bool(args.proposal)))
    print('Saved public synthetic teaching CSV:', out)


if __name__ == '__main__':
    main()

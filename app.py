import streamlit as st
from collections import Counter
import random
import numpy as np
import string
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d.art3d import Poly3DCollection
import io


st.set_page_config(
    page_title="Load Optimizer",
    page_icon="images/sentics_logo.png",
    layout='wide'
)

st.logo("images/sentics.png",size="large")
_,name_col,_=st.columns([1,2,1])
with name_col:
    st.image(image="images/schnellecke.png")
# Data
container = {"Mega Trailer":{"length":13600,"width":2500, "height":2700},
             "Conventional Trailer":{"length":13600,"width":2500, "height":3000}}
load = {"1057730 RKN + 2 LHM FUEHR-WAG":{"length":2550,"width":850, "height":665, "weight":373.134, "pallet_type":"RKN"},
        "1186892 RKH + 26 LHM QUERB":{"length":2550,"width":850, "height":965, "weight":535.364, "pallet_type":"RKH"},
        "1279747 EWP":{"length":3186,"width":730, "height":560, "weight":387.304, "pallet_type":"EWP"},
        "1186893 RKH + 26 LHM QUERB":{"length":2570,"width":850, "height":965, "weight":537.548, "pallet_type":"RKH"},}

# Weight chart
chart = [
    (0, 9000),(1000, 11000),(2000, 13000),(3000, 15000),(4000, 17000),(5000, 18000),(6000, 21000),
    (7000, 28000),(8000, 28000),(8500,21000),(9000, 9000),(9500, 4000),(10000, 3000),(11000, 2000),
    (12000, 1000),(13000, 1000),(14000, 1000)
]

# Forbidden
forbidden_on = {
    "EWP": {"RKN","RKH"},
    "RKN":{"EWP"},
     "RKH":{"EWP"}
}

def allowed_weight_at_x(x, chart):
    for (x1, w1), (x2, w2) in zip(chart, chart[1:]):
        if x1 <= x <= x2:
            return w1 + (w2 - w1) * (x - x1) / (x2 - x1)
    return chart[-1][1]


def compute_x_weight_bins(placements, bin_size=1000, x_max=14000):
    bins = {x: 0.0 for x in range(0, x_max + bin_size, bin_size)}

    for p in placements:
        x0, x1 = p["x"], p["x_e"]
        w = p["weight"]
        L = x1 - x0
        if L <= 0:
            continue

        for b in bins:
            overlap = max(0, min(x1, b + bin_size) - max(x0, b))
            if overlap > 0:
                bins[b] += w * overlap / L

    return bins

def overlaps(a, b):
    return not (
        a["x_e"] <= b["x"] or b["x_e"] <= a["x"] or
        a["y_e"] <= b["y"] or b["y_e"] <= a["y"] or
        a["z_e"] <= b["z"] or b["z_e"] <= a["z"]
    )

def has_corner_support(candidate, placements):
    for p in placements:
        if p["z_e"] >= candidate["z"]:
            x_overlap = min(candidate["x_e"], p["x_e"]) - max(candidate["x"], p["x"])
            y_overlap = min(candidate["y_e"], p["y_e"]) - max(candidate["y"], p["y"])
            if x_overlap <= 0 or y_overlap <= 0:
                continue
            if candidate["l"] > p["l"] + 40:
                continue
            if candidate["w"] > p["w"] + 40:
                continue
            return True
    return False

def violates_forbidden(candidate, placements, forbidden_on):
    for p in placements:
        if p["z_e"] == candidate["z"]:

            x_overlap = min(candidate["x_e"], p["x_e"]) - max(candidate["x"], p["x"])
            y_overlap = min(candidate["y_e"], p["y_e"]) - max(candidate["y"], p["y"])

            if x_overlap > 0 and y_overlap > 0:

                top = candidate["pallet_type"]
                bottom = p["pallet_type"]

                if top in forbidden_on:
                    if bottom in forbidden_on[top]:
                        return True

    return False

def sort_rows_by_height(placements, container_type):
    c = container[container_type]
    ROW_HEIGHT = c["width"] / 3
    GAP = 100
    START_X = 30

    rows = {0: [], 1: [], 2: []}

    # Split into rows
    for p in placements:
        band = int(((p["y"] + p["y_e"]) / 2) // ROW_HEIGHT)
        band = min(band, 2)
        rows[band].append(p)

    result = []

    for band in rows:
        cols = {}

        for p in rows[band]:
            cols.setdefault(p["x"], []).append(p)

        ordered_cols = sorted(
            cols.values(),
            key=lambda col: -sum(i["h"] for i in col)
        )

        new_x = START_X

        for col in ordered_cols:
            col.sort(key=lambda p: p["z"]) 

            z_cursor = 0
            for p in col:
                width = p["l"]

                p["x"] = new_x
                p["x_e"] = new_x + width
                p["z"] = z_cursor
                p["z_e"] = z_cursor + p["h"]

                z_cursor += p["h"]
                result.append(p)

            new_x += width + GAP

    return result

def pack_once(container_type, items, chart, forbidden_on):
    c = container[container_type]

    free_spaces = [{
        "type": "front",
        "x": 30, "y": 30, "z": 0,
        "l": c["length"], "w": c["width"], "h": c["height"]
    }]

    placements = []

    col_height = {}
    col_cap = {0: c["height"]}

    row_height = {}
    row_cap = {0: c["height"]}

    items = sorted(items, key=lambda x: x[1]["length"])

    for name, box in items:
        
        free_spaces.sort(key=lambda s: {"front": 0, "top": 1, "right": 2}[s["type"]])

        for space in free_spaces[:]:
            col_x = space["x"]
            row_y = space["y"]

            cap_x = col_cap.get(col_x, c["height"])
            cap_y = row_cap.get(row_y, c["height"])
            cap = min(cap_x, cap_y)

            for l, w, h in [
                (box["length"], box["width"], box["height"]),
                (box["width"], box["length"], box["height"])
            ]:

                if l > space["l"] or w > space["w"] or h > space["h"]:
                    continue

                if space["z"] + h > cap:
                    continue

                new_h = space["z"] + h

                def max_allowed_height_at_x(col_x, col_height, container_height):
                    left = [h for x, h in col_height.items() if x < col_x]
                    return left[-1] if left else container_height

                def max_allowed_height_at_y(row_y, row_height, container_height):
                    left = [h for x, h in row_height.items() if x < row_y]
                    return left[-1] if left else container_height

                allowed_h = max_allowed_height_at_x(col_x, col_height, c["height"])
                if new_h > allowed_h:
                    continue

                allowed_h_y = max_allowed_height_at_y(row_y, row_height, c["height"])
                if new_h > allowed_h_y:
                    continue

                candidate = {
                    "item": name,
                    "x": space["x"], "y": space["y"], "z": space["z"],
                    "l": l, "w": w, "h": h,
                    "x_e": space["x"] + l,
                    "y_e": space["y"] + w,
                    "z_e": space["z"] + h,
                    "weight": box["weight"],
                    "pallet_type": box["pallet_type"]
                }

                if any(overlaps(candidate, p) for p in placements):
                    continue

                if violates_forbidden(candidate, placements, forbidden_on):
                    continue

                trial = placements + [candidate]
                max_x = max(p["x_e"] for p in trial)
                bins = compute_x_weight_bins(trial, x_max=max_x)

                if any(bins[x] > allowed_weight_at_x(x + 500, chart) for x in bins):
                    continue

                if space["type"] == "top":
                    if not has_corner_support(candidate, placements):
                        continue

                placements.append(candidate)
                free_spaces.remove(space)

                col_height[col_x] = max(col_height.get(col_x, 0), new_h)
                row_height[row_y] = max(row_height.get(row_y, 0), new_h)

                col_cap[col_x + l] = col_height[col_x]
                row_cap[row_y + w] = row_height[row_y]

                free_spaces.append({
                    "type": "top",
                    "x": space["x"],
                    "y": space["y"],
                    "z": new_h,
                    "l": space["l"], "w": space["w"],
                    "h": cap - new_h
                })

                free_spaces.append({
                    "type": "right",
                    "x": space["x"] + l + 100,
                    "y": space["y"], "z": 0,
                    "l": c["length"] - (space["x"] + l + 100),
                    "w": space["w"],
                    "h": col_height[col_x]
                })

                if space["type"] == "front" and space["w"] > w:
                    free_spaces.append({
                        "type": "front",
                        "x": space["x"],
                        "y": space["y"] + w + 30,
                        "z": space["z"],
                        "l": space["l"],
                        "w": space["w"] - w - 30,
                        "h": row_height[row_y]
                    })

                break
            else:
                continue
            break

    return placements

def pack_3d(container_type, items, chart, forbidden_on, runs=50):
    best = []
    best_score = (-1, -1)

    for _ in range(runs):
        shuffled = items[:]
        random.shuffle(shuffled)

        placements = pack_once(container_type, shuffled, chart, forbidden_on)
        score = (len(placements), sum(p["weight"] for p in placements))

        if score > best_score:
            best = placements
            best_score = score

    placed_counts = Counter(p["item"] for p in best)
    total_counts = Counter(i[0] for i in items)

    unplaced_counts = {}
    for item, total in total_counts.items():
        unplaced_counts[item] =total - placed_counts.get(item, 0)

    best = sort_rows_by_height(best, container_type)
    best.sort(key=lambda p: (p["x"], p["y"], -(p["l"]+p["w"]), -p["weight"]))
    z_at = {}
    for p in best: 
        k = (p["x"], p["y"])
        p["z"] = z_at.get(k, 0)
        p["z_e"] = p["z"] + p["h"]
        z_at[k] = p["z_e"]
    return best, unplaced_counts, placed_counts

def cuboid_faces_from_extents(x, y, z, x_e, y_e, z_e):
    v = [
        [x,   y,   z],
        [x_e, y,   z],
        [x_e, y_e, z],
        [x,   y_e, z],
        [x,   y,   z_e],
        [x_e, y,   z_e],
        [x_e, y_e, z_e],
        [x,   y_e, z_e],
    ]
    return [
        [v[0], v[1], v[5], v[4]], 
        [v[3], v[2], v[6], v[7]],  
        [v[0], v[1], v[2], v[3]], 
        [v[4], v[5], v[6], v[7]],  
        [v[1], v[2], v[6], v[5]],  
        [v[0], v[3], v[7], v[4]],  
    ]

# Session state
if "page" not in st.session_state:
    st.session_state.page = "input"
if "container_selected" not in st.session_state:
    st.session_state["container_selected"] = None
if "quantities" not in st.session_state:
    st.session_state["quantities"] = {}

# Main input state
if st.session_state.page == "input":
    warning = False
    mc1,mc2 = st.columns([0.5,1])
    with mc1:
        st.write("**Forbidden Placement**")
        for forbidden_key,forbidden_value in forbidden_on.items():
            st.write(f"{forbidden_key}: {', '.join(forbidden_value)}")
    with mc2:
        container_key = [k for k in container.keys()]
        keys = [k for k in load.keys()]
        container_selected = st.selectbox("**Select Container**", container_key,index=None, placeholder="Select a container",key="container_selected")
        selected = st.selectbox("**Select item key**", keys,index=None, placeholder="Select an item")

        st.session_state.setdefault("quantities", {})
        if selected is not None:
            current_value = st.session_state["quantities"].get(selected, 0)

            qty = st.number_input(
                f"**Enter quantity for {selected}**",
                min_value=0,
                step=1,
                value=current_value
            )
        else:
            qty = 0
    
    c1,c2=st.columns(2)
    with c1:
        if selected is not None and qty > 0:
            st.session_state["quantities"][selected] = qty
        elif selected in st.session_state["quantities"]:
            del st.session_state["quantities"][selected]
        st.markdown("###### Saved Quantities")
        st.write(f'Container : {st.session_state["container_selected"]} ')
        for k, v in st.session_state["quantities"].items():
            st.write(f"- {k} : {v}")
    with c2:
        c1_main,c2_main,_,_=st.columns([2,3,1,3])
        with c1_main:
            if st.button("Next", key="nav_next"):
                if not st.session_state["quantities"] and st.session_state["container_selected"] is None:
                    warning = True
                    msg = "both"
                elif not st.session_state["quantities"]:
                    warning = True
                    msg = "items"
                elif st.session_state["container_selected"] is None:
                    warning = True
                    msg = "container"
                else:
                    st.session_state.page = "result"
                    st.rerun()
        with c2_main:
            if st.button("Clear", key="c_clear"):
                st.session_state["quantities"].clear()
                st.session_state.pop("container_selected", None)
                st.rerun()
                warning = False 
                st.rerun()

    warning_msg = {"items":"Please add items to the container to optimize...",
                   "container":"Please select container to optimize...",
                   "both":"Please select container and add items to optimize..."}
    if warning:
        st.warning(warning_msg.get(msg))

# Page 2 result
elif st.session_state.page == "result":
    if st.button("New", key="new"):
        st.session_state.page = "input"
        del st.session_state["quantities"] 
        del st.session_state["container_selected"] 
        st.rerun()
    items = []
    for k, q in st.session_state["quantities"].items():
        for _ in range(q):
            items.append((k, load[k]))
    with st.spinner("Finding the best result and plotting it..."):
        placements,un, assigned_items = pack_3d(st.session_state["container_selected"], items,chart,forbidden_on)
        weight = sum([p['weight'] for p in placements])
        volume = (sum(p['l']*p["w"]*p['h'] for p in placements))/1e9
        remaining_volume = (container[st.session_state["container_selected"]]['length']*container[st.session_state["container_selected"]]['width']*container[st.session_state["container_selected"]]['height'])/1e9 - volume
        denote = {key:string.ascii_uppercase[N] for N,key in enumerate(load.keys())}

        x_max = container[st.session_state["container_selected"]]["length"]  
        y_max = container[st.session_state["container_selected"]]["width"]   
        z_max = container[st.session_state["container_selected"]]["height"]

        NUM_ROWS = 3
        ROW_HEIGHT = y_max / NUM_ROWS
        bands = {0: [], 1: [], 2: []}

        for p in placements:
            y_center = (p["y"] + p["y_e"]) / 2
            band_index = int(y_center // ROW_HEIGHT)
            band_index = min(band_index, NUM_ROWS - 1)
            bands[band_index].append(p)

        band_counts = {k: len(v) for k, v in bands.items()}
        existing_bands = [k for k, v in band_counts.items() if v > 0]

        band_metrics = {}

        for band, items in bands.items():
            if not items:
                band_metrics[band] = (0, 0)
            else:
                max_x = max(p["x_e"] for p in items)
                total_height = sum(p["h"] for p in items)
                band_metrics[band] = (max_x, total_height)

        sorted_bands = sorted(
            band_metrics.items(),
            key=lambda x: (-x[1][0], -x[1][1])
        )

        band_remap = {}
        for new_row_index, (original_band, _) in enumerate(sorted_bands):
            band_remap[original_band] = new_row_index

        for b in bands.keys():
            if b not in band_remap:
                band_remap[b] = len(band_remap)

        band_new_y_start = {}
        for original_band in range(NUM_ROWS):
            new_row_index = band_remap[original_band]
            band_new_y_start[original_band] = new_row_index * ROW_HEIGHT

        views = {
            "3D Overview": "all",
            "Row 1": 0,
            "Row 2": 1,
            "Row 3": 2,
            "Top View": "all",
        }

        row_colors = {
            0: "blue",
            1: "red",
            2: "green"
        }

        view_angles = {
            "3D Overview": (30, 110),
            "Row 1": (0, 90),
            "Row 2": (0, 90),
            "Row 3": (0, 90),
            "Top View": (90, 90),
        }

        fig = plt.figure(figsize=(20, 12))

        for i, title in enumerate(views.keys(), 1):
            ax = fig.add_subplot(3, 4, i, projection="3d")

            for p in placements:

                y_center = (p["y"] + p["y_e"]) / 2
                original_band = int(y_center // ROW_HEIGHT)
                original_band = min(original_band, NUM_ROWS - 1)

                new_row_index = band_remap[original_band]
                if isinstance(views[title], int):
                    if new_row_index != views[title]:
                        continue

                if title in ["3D Overview", "Top View"]:
                    band_offset = band_new_y_start[original_band]
                    local_y_offset = p["y"] - (original_band * ROW_HEIGHT)

                    y_plot = band_offset + local_y_offset
                    y_e_plot = y_plot + (p["y_e"] - p["y"])
                else:
                    y_plot = p["y"]
                    y_e_plot = p["y_e"]

                faces = cuboid_faces_from_extents(
                    p["x"], y_plot, p["z"],
                    p["x_e"], y_e_plot, p["z_e"]
                )

                color = row_colors.get(new_row_index, "gray")

                ax.add_collection3d(Poly3DCollection(
                        faces,
                        facecolor=color,
                        edgecolor="k",
                        alpha=0.35,
                        zsort='average'

                    )
                )

                cx = (p["x"] + p["x_e"]) / 2
                cy = (y_plot + y_e_plot) / 2
                cz = p["z_e"] - 350

                ax.text(
                    cx, cy, cz,
                    denote.get(p["item"]),
                    ha="center",
                    va="center",
                    fontsize=9,
                    fontweight="bold",
                    color="black"
                )

            ax.set_yticks([])
            ax.yaxis.pane.set_visible(False)
            ax.zaxis.pane.set_visible(False)

            elev, azim = view_angles[title]
            ax.view_init(elev=elev, azim=azim)

            ax.set_title(title)
            ax.set_xlim(x_max, 0)
            ax.set_ylim(0, y_max)
            ax.set_zlim(0, z_max)
            ax.set_box_aspect((x_max, y_max, z_max))
            ax.set_xlabel("X")
        ax = fig.add_subplot(3, 4, 6)
        x_bins = compute_x_weight_bins(placements, 1000, 14000)

        xs = []
        loads = []
        allowed = []

        for x in range(0, x_max, 1000):
            xs.append(x + 500) 
            loads.append(x_bins.get(x, 0.0))
            allowed.append(allowed_weight_at_x(x + 500, chart))
        ax.plot(xs, allowed, label="Allowed Weight", color="red", linestyle="--")
        ax.plot(xs, loads, label="Occupied Weight", color="green",linestyle="--")
        ax.set_xlabel("Length (mm)")
        ax.set_ylabel("Weight (Kg)")
        ax.set_title("Distribution Curve")
        ax.legend()
        ax.grid(True)
    
        legend_text = "\n".join(f"{k} = {v} : {assigned_items.get(k, 0)} assigned, {un.get(k, 0)} unassigned" for k,v in denote.items())
        legend_text_with_title = (
            f"Container type: {st.session_state['container_selected']}\n"
            "-------------------------------------------------------------\n"
            "Container to symbol relation with the quantity of items assigned and unassigned\n"
            "-------------------------------------------------------------\n"
            f"{legend_text}\n"
            "-------------------------------------------------------------\n"
            "Container Satistics\n"
            "-------------------------------------------------------------\n"
            f"Load Weight: {weight:.2f} kg\n"
            f"Container Occupier Volume: {volume:.2f} m³\n"
            f"Container Remaining Volume: {remaining_volume:.2f} m³\n"
            "-------------------------------------------------------------\n"
        )
        fig.text(
            0.6, 0.5,
            legend_text_with_title,
            fontsize=11,
            va="center",
            ha="left"

        )
        plt.tight_layout()
        st.pyplot(fig)
        plt.close(fig)


    

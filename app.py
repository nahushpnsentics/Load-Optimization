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
    page_icon="images/sentics_logo.png"
)

st.logo("images/sentics.png",size="large")
_,name_col,_=st.columns([1,2,1])
with name_col:
    st.image(image="images/schnellecke.png")
# Data
container = {"Mega Trailer":{"length":13600,"width":2500, "height":2700},
             "Conventional Trailer":{"length":13600,"width":2500, "height":3000}}
load = {"1057730 RKN + 2 LHM FUEHR-WAG":{"length":2550,"width":850, "height":665, "weight":373.134},
        "1186892 RKH + 26 LHM QUERB":{"length":2550,"width":850, "height":965, "weight":535.364},
        "1279747 EWP":{"length":3186,"width":730, "height":560, "weight":387.304},
        "1186893 RKH + 26 LHM QUERB":{"length":2570,"width":850, "height":965, "weight":537.548},}

# Weight chart
chart = [
    (0, 9000),(1000, 11000),(2000, 13000),(3000, 15000),(4000, 17000),(5000, 18000),(6000, 21000),
    (7000, 28000),(8000, 28000),(8500,21000),(9000, 9000),(9500, 4000),(10000, 3000),(11000, 2000),
    (12000, 1000),(13000, 1000),(14000, 1000)
]


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


def pack_once(container_type, items, chart):
    c = container[container_type]

    free_spaces = [{
        "type": "front",
        "x": 50, "y": 50, "z": 0,
        "l": c["length"], "w": c["width"], "h": c["height"]
    }]

    placements = []

    col_height = {}
    col_cap = {0: c["height"]}

    row_height = {}
    row_cap = {0: c["height"]}
    avg_length = sum(b["length"] for _, b in items) / len(items)
    count =0
    active_row_y =0
    for _, b in items:
        if b["length"] >= avg_length:
            count += 1
    if count < 4:
        items = sorted(items, key=lambda x: (-x[1]["length"]*x[1]["width"]*x[1]["height"],-x[1]["length"]))

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
                if space["y"] < active_row_y:
                    continue
                if space["z"] + h > cap:
                    continue

                new_h = space["z"] + h

                def max_allowed_height_at_x(col_x, col_height, container_height):
                    left = [h for x, h in col_height.items() if x < col_x]
                    return (left[-1]) if left else container_height
                def max_allowed_height_at_y(row_y, row_height, container_height):
                    left = [h for x, h in row_height.items() if x < row_y]
                    return (left[-1]) if left else container_height
                allowed_h = max_allowed_height_at_x(col_x, col_height, c["height"])
                if new_h > allowed_h:
                    continue
                allowed_h_y = max_allowed_height_at_y(row_y, row_height, c["height"])
                if new_h > allowed_h_y:
                    continue


                left_heights = [
                    h for x, h in col_height.items()
                    if x < col_x
                ]

                if left_heights:
                    max_left_height = max(left_heights)
                    if new_h > max_left_height:
                        continue
                candidate = {
                    "item": name,
                    "x": space["x"], "y": space["y"], "z": space["z"],
                    "l": l, "w": w, "h": h,
                    "x_e": space["x"] + l,
                    "y_e": space["y"] + w,
                    "z_e": space["z"] + h,
                    "weight": box["weight"]
                }

                if any(overlaps(candidate, p) for p in placements):
                    continue

                trial = placements + [candidate]
                max_x = max(p["x_e"] for p in trial)
                bins = compute_x_weight_bins(trial, x_max=max_x)

                if any(bins[x] > allowed_weight_at_x(x + 500, chart) for x in bins):
                    continue
                if space["type"] == "top":
                    if not has_corner_support(candidate, placements):
                        continue

                placements.append(
                    candidate
                )

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
                        "y": space["y"] + w + 100,
                        "z": space["z"],
                        "l": space["l"],
                        "w": space["w"] - w - 100,
                        "h": row_height[row_y]
                    })

                break
            else:
                continue
            break

    return placements

def pack_3d(container_type, items, chart, runs=100):
    best = []
    best_score = (-1, -1)

    for _ in range(runs):
        shuffled = items[:]
        random.shuffle(shuffled)

        placements = pack_once(container_type, shuffled, chart)
        score = (len(placements), sum(p["weight"] for p in placements))
        
        if score > best_score:
            best = placements
            best_score = score
    
    placed_counts = Counter(p["item"] for p in best)
    total_counts  = Counter(i[0] for i in items)
    unplaced_counts = {}
    for item, total in total_counts.items():
        unplaced_counts[item] =total - placed_counts.get(item, 0)
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
    container_key = [k for k in container.keys()]
    keys = [k for k in load.keys()]
    container_selected = st.selectbox("Select Container", container_key,index=None, placeholder="Select a container",key="container_selected")
    selected = st.selectbox("Select item key", keys,index=None, placeholder="Select an item")

    st.session_state.setdefault("quantities", {})
    if selected is not None:
        current_value = st.session_state["quantities"].get(selected, 0)

        qty = st.number_input(
            f"Enter quantity for {selected}",
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
        st.markdown("### Saved Quantities")
        st.write(f'**Container** : {st.session_state["container_selected"]} ')
        for k, v in st.session_state["quantities"].items():
            st.write(f"- **{k}** : {v}")
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
        placements,un, assigned_items = pack_3d(st.session_state["container_selected"], items,chart)
        weight = sum([p['weight'] for p in placements])
        volume = (sum(p['l']*p["w"]*p['h'] for p in placements))/1e9
        remaining_volume = (container[st.session_state["container_selected"]]['length']*container[st.session_state["container_selected"]]['width']*container[st.session_state["container_selected"]]['height'])/1e9 - volume
        denote = {key:string.ascii_uppercase[N] for N,key in enumerate(load.keys())}

        x_max = container[st.session_state["container_selected"]]["length"]  
        y_max = container[st.session_state["container_selected"]]["width"]   
        z_max = container[st.session_state["container_selected"]]["height"]

        Y_SPLIT = y_max / 2
        views = {
            "3D Overview": "all",
            "First Row": "below",
            "Second Row": "above",
            "Top View": "all",
        }

        view_angles = {
            "3D Overview": (25, 140),
            "First Row": (0, 90),
            "Second Row": (0, 90),
            "Top View": (90, 90),
        }

        fig = plt.figure(figsize=(18, 10))

        for i, title in enumerate(views.keys(), 1):
            ax = fig.add_subplot(2, 3, i, projection="3d")

            for p in placements:
                y_center = (p["y"] + p["y_e"]) / 2

                if views[title] == "above" and y_center < Y_SPLIT:
                    continue
                if views[title] == "below" and y_center >= Y_SPLIT:
                    continue

                faces = cuboid_faces_from_extents(
                    p["x"], p["y"], p["z"],
                    p["x_e"], p["y_e"], p["z_e"]
                )

                color = "red" if y_center >= Y_SPLIT else "blue"

                ax.add_collection3d(
                    Poly3DCollection(
                        faces,
                        facecolor=color,
                        edgecolor="k",
                        alpha=0.35
                    )
                )

                # Label
                cx = (p["x"] + p["x_e"]) / 2
                cy = (p["y"] + p["y_e"]) / 2
                cz = p["z_e"]-350 

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
        ax = fig.add_subplot(2, 3, 5)
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
        for num,( x, y) in enumerate(zip(xs, loads)):
            if num%2==0:
                ax.text(x+200, y+500 , f"{y:.2f}", ha="center", fontsize=9, weight="bold")
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
            0.7, 0.3,
            legend_text_with_title,
            fontsize=11,
            va="center",
            ha="left"

        )
        plt.tight_layout()
        st.pyplot(fig)
        plt.close(fig)


    

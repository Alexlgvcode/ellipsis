# ellipsis — Production UI / UX Design Specification
## Finalized first-pass direction for Claude Design / implementation

**Product:** ellipsis  
**Purpose:** Real-time urban traffic incident detection, monitoring, and signal-response simulation for New York City  
**Primary environment:** Desktop operations interface  
**Primary users:** Traffic operations teams, transportation analysts, demo users / judges  
**Design direction:** **35% control-room / infrastructure, 65% urban-intelligence platform**

---

# 1. Product design thesis

`ellipsis` should feel like a modern urban intelligence platform built for real operational use.

The interface should be:

- map-first
- spatial
- calm
- modern
- dense where useful
- visually memorable without becoming flashy
- credible enough to feel deployable
- minimal at rest and richer on interaction
- strongly legible even with many incidents
- animated only when state changes or a simulation is running

The visual goal is:

> **A live NYC traffic intelligence system with the clarity of infrastructure software and the spatial sophistication of a modern geospatial platform.**

Do not make the product look like:
- a generic SaaS dashboard
- a hackathon card grid
- an AI assistant
- a cyberpunk traffic control UI
- a surveillance wall
- a game
- a Google Maps clone

---

# 2. Brand

## 2.1 V1 wordmark

Use:

`ellipsis • • •`

- all lowercase
- Geist
- near-black wordmark
- three small dots immediately after the word
- dots: red, amber, green
- dots should feel like punctuation, not emoji traffic lights

Brand dot colors:
- red: `#D84C4C`
- amber: `#D99A2B`
- green: `#3E9B6C`

Do not create a standalone logo for v1.

A dedicated logo can be designed later after the product language is established.

## 2.2 Brand behavior

Use the three dots for:
- wordmark
- initial loading
- simulation loading
- major geography transitions if needed

Do not repeat the dots decoratively across the UI.

---

# 3. Typography

Primary UI font:
- **Geist**

Monospace:
- **Geist Mono**

Use Geist for:
- headings
- labels
- location names
- navigation
- buttons
- body copy

Use Geist Mono for:
- time
- elapsed duration
- camera ID
- data freshness
- confidence
- machine metrics
- simulation numbers

Avoid:
- serif fonts
- typewriter styling
- terminal aesthetic
- mono headings

Suggested scale:

- wordmark: 18px / 600
- top-level app text: 14px / 500
- incident title: 18–20px / 600
- section title: 13px / 600
- body: 13px / 400
- secondary: 12px / 400
- machine metadata: 11–13px mono
- key metric: 20–26px / 600

---

# 4. Color system

## 4.1 Neutral surfaces

```text
Canvas                  #F4F2ED
Panel                   #FBFAF7
Raised panel            #FFFFFF
Subtle section fill     #F7F5F0
Border                  #DDD9D1
Border strong           #C9C4BB
```

## 4.2 Text

```text
Primary                 #1B1D1B
Secondary               #606660
Muted                   #858B85
Disabled                #A7ACA7
Inverse                 #FAFAF7
```

## 4.3 Semantic color

Healthy / good:
```text
Healthy                 #2F8F62
Healthy soft            #E5F2EA
Healthy border          #BFDCCB
```

Needs attention / degraded:
```text
Amber                   #C88A22
Amber soft              #F7ECD5
Amber border            #E6C98E
```

Confirmed incident:
```text
Incident coral          #E7644C
Incident soft           #F9E5DF
Incident border         #F0B6AA
```

Critical / severe:
```text
Critical red            #C9473D
Critical soft           #F6DFDC
Critical border         #E7A6A0
```

Neutral selection:
```text
Selected fill           #ECE9E3
Selected border         #AAA49A
Selected text           #1B1D1B
```

## 4.4 Important semantic rule

**Most of the product should be neutral. Color only appears when communicating state.**

Do not use teal as the generic accent or selection color.

Green/teal is reserved for:
- healthy camera
- live feed
- resolved incident
- system healthy
- positive simulation result

---

# 5. Core desktop architecture

Desktop layout:

```text
┌─────────────────────────────────────────────────────────────────────────────────────────────┐
│ ellipsis ● ● ●    New York City / Manhattan / Midtown ▾      12 incidents  96.8% cameras  LIVE ●  18:24 │
├───────────────────┬─────────────────────────────────────────────────────────────────────────┤
│ ACTIVE INCIDENTS  │                                                                         │
│                   │                                                                         │
│ compact queue     │                           3D CITY MAP                                   │
│                   │                                                                         │
│                   │                                                                         │
│                   │                                                      ┌────────────────┐ │
│                   │                                                      │ incident       │ │
│                   │                                                      │ inspector      │ │
│                   │                                                      │ floating       │ │
│                   │                                                      └────────────────┘ │
│                   │                                                                         │
│                   │ [Incidents ✓] [Traffic ✓] [Cameras] [Signals]              [+]          │
│                   │                                                        [−] [3D] [⟳]      │
└───────────────────┴─────────────────────────────────────────────────────────────────────────┘
```

Important:
- do **not** use a rigid 3-column dashboard
- the map is the canvas
- the inspector floats above the map
- the right side is not permanently occupied
- when nothing is selected, the map gets the full right side

---

# 6. Top bar

Height:
- **56px**

Contents:

Left:
- `ellipsis • • •`
- geography breadcrumb

Right:
- active incident count
- camera health
- live/system state
- current time

Example:

```text
ellipsis • • •     New York City / Manhattan / Midtown ▾

12 incidents     96.8% cameras     LIVE ●     18:24
```

Rules:
- no large pills
- no metric cards
- no search bar in v1
- use spacing and subtle separators
- `LIVE` is green only when current
- camera-health text can become amber if degraded

Geography uses `/`, not `>`.

---

# 7. Default first-load state

When the user opens ellipsis:

- show Manhattan in 3D
- medium map pitch
- several subtle incident markers visible
- incident rail populated
- no incident inspector open
- traffic overlay lightly active
- cameras hidden unless camera layer is enabled
- no giant onboarding state
- no modal
- map is immediately usable

The product should feel city-scale immediately.

Default geography:
- Manhattan-wide or Midtown-focused depending demo scenario
- enough context to prove citywide scalability

---

# 8. 3D map direction

3D is part of the ellipsis identity.

Do not remove it.

Use:
- moderate 45–55° pitch at corridor scale
- lower pitch citywide
- restrained extrusion
- low-saturation architectural colors
- no satellite imagery
- no photorealism
- no dramatic shadows

Map palette:

```text
Ground                   #EEEAE2
Road                     #FAF8F3
Road secondary           #F2EFE9
Building top             #D9D2C7
Building side            #C8C0B4
Park                     #DCE6D7
Water                    #D8E4E7
Street label             #767B75
Minor label              #9A9F99
```

Map should feel alive but not gray or sterile.

### Zoom behavior

City / borough:
- low pitch
- almost-flat buildings
- incident clustering

Corridor:
- medium pitch
- full restrained 3D
- incident markers
- traffic degradation
- selected road segments

Intersection:
- slightly closer
- strongest spatial detail
- camera + incident relationship
- lane context where available

---

# 9. Map interaction philosophy

**Minimalist at rest. Richer on interaction.**

Default:
- neutral city
- thin incident markers
- minimal labels
- no glowing overlays

When selected:
- selected incident label appears
- affected road segment highlights
- camera source is revealed
- downstream impact can fade in
- inspector opens

No continuous visual noise.

---

# 10. Incident rail

Width:
- **288px**

Purpose:
- triage, not investigation

No thumbnails.

### Header

```text
ACTIVE INCIDENTS                         12

Critical 2   Review 3   All 12
Sort: Severity
```

Do not use oversized tabs or pill buttons.

### Row

Target height:
- 76–84px

Example:

```text
●  8th Ave @ W 33rd St
   Double parked
   04:15                      +22s
```

Show:
- location
- incident type
- elapsed time
- estimated added delay

Do not show confidence in the rail.

### Severity

- amber: needs review
- coral: confirmed
- deep red: critical
- green: resolved
- healthy cameras do not appear as incidents

### Selected state

Use:
- warm neutral fill
- 2px semantic border at left
- no teal selection

### 30+ incidents

Support:
- virtualized scrolling
- sticky header
- grouping by severity when sorted by severity

### Collapse

Desktop rail may collapse to ~48px.

Collapsed state keeps:
- incident count
- severity indicator
- expand affordance

---

# 11. Incident markers

Default confirmed incident:
- small coral circle
- subtle neutral ring
- no glow
- no continuous pulse

Needs review:
- amber circle

Critical:
- deep red
- slightly larger or stronger outline

Selected:
- same semantic color
- neutral outer ring
- thin affected-road highlight
- label

New incident:
- one small pulse only

---

# 12. Camera markers

Healthy camera:
- tiny green dot
- visible only when camera layer is enabled or incident needs it

Stale:
- gray

Offline:
- gray / neutral slash state

Incident source camera:
- slightly larger
- stays green if live
- surfaced only after incident selection

Do not show all camera labels.

---

# 13. Road-state visualization

Default roads remain neutral.

Only degraded / incident-relevant segments gain color.

```text
Moderate degradation      #D2A14C
Heavy degradation         #D96A4B
Severe congestion         #C9473D
```

Use thin overlays.

Do not create a full Google-Maps-style traffic rainbow.

When an incident is selected:
- show affected road segment
- optionally show light downstream propagation
- keep impact visualization sparse and readable

---

# 14. Floating incident inspector

Desktop:
- width: **380px**
- right offset: 20–24px
- top offset: 76–84px
- max-height: viewport minus header + margin

Surface:
- warm off-white
- 1px neutral border
- 10–12px radius
- subtle shadow
- no glass blur
- no gradient border
- no giant cards inside cards

The panel should feel like a GIS / operations inspector.

---

# 15. Inspector hierarchy

Default order:

1. Incident
2. Live camera feed
3. Traffic impact
4. Recommended response
5. Detection details
6. Timeline

Example:

```text
┌────────────────────────────────────┐
│ CONFIRMED                      ×   │
│ Double parked vehicle              │
│ 8th Ave @ W 33rd St                │
│ 04:15                  84% conf.   │
│ CAM-8AV-033        LIVE ●   2s old │
├────────────────────────────────────┤
│                                    │
│          LIVE CAMERA FEED          │
│                                    │
│        [ restrained overlay ]      │
│                                    │
│ 18:49:21 EDT                       │
├────────────────────────────────────┤
│ Traffic impact                     │
│ +22s delay      9 vehicles queued  │
│ -34% capacity   -18% speed         │
├────────────────────────────────────┤
│ Recommended response               │
│ Signal timing simulation           │
│ Projected: -19% avg delay          │
│                      Open sim →    │
├────────────────────────────────────┤
│ Detection details             ›    │
│ Timeline                      ›    │
└────────────────────────────────────┘
```

---

# 16. Live camera feed

This is a **live operational feed**, not a static evidence thumbnail.

Must show:
- camera ID
- current/live state
- freshness
- timestamp
- restrained detection overlay

Example:

```text
CAM-8AV-033      LIVE ●   2s old
```

If source is periodic snapshots:
- use `Live camera · updated 3s ago`
- do not falsely call it live video

Controls:
- Live
- -30s
- -60s
- Replay

Replay state:
```text
REPLAY · 18:48:32
```

Delayed:
```text
CAM-8AV-033      DELAYED · 18s
```

Offline:
```text
CAM-8AV-033      OFFLINE
Last frame 18:46:03
```

### Overlay

Default overlay:
- thin bounding box
- small event label
- timestamp

Avoid:
- segmentation masks
- trajectory spam
- giant confidence badges
- “AI DETECTED” banners

---

# 17. Camera-to-incident relationship

When an incident is selected:
- source camera becomes visible
- camera marker enlarges slightly
- a faint directional tether can fade in briefly
- tether should not remain visually dominant
- incident remains the center of the map

Interaction rule:

> **Incident selection centers the obstruction. Camera inspection reveals the source.**

Clicking the source camera may shift the view enough to show both source and incident.

---

# 18. Detection details

Collapsed by default.

Expanded:

```text
Detection details

stationary duration       255s
travel lane                yes
curb offset               1.2m
motion score              0.08
threshold                  60s
```

Do not use prose like:
- “Our AI believes…”
- “Smart detection insight”
- “AI confidence engine”

Plain machine state only.

---

# 19. Traffic impact

Use aligned rows, not KPI cards.

Example:

```text
Traffic impact

added delay              +22s
queue estimate      9 vehicles
lane capacity            -34%
downstream speed         -18%
```

---

# 20. Recommended response

Label:
- **Recommended response**

Content:
- `Signal timing simulation`
- projected effect
- clear CTA

Example:

```text
Recommended response

Signal timing simulation

Current       48.1s
Proposed      38.9s

Projected improvement      -19%

Open simulation →
```

Use green only for positive delta.

Do not call it:
- AI recommendation
- smart optimization
- intelligent action

---

# 21. Simulation experience

Simulation expands into a **focused scenario mode**.

It should not stay trapped in the 380px inspector.

Flow:

1. click `Open simulation`
2. inspector recedes
3. map becomes focused
4. `ellipsis • • •` branded loading transition
5. baseline runs
6. recommended signal changes introduced
7. traffic behavior changes
8. result metrics settle
9. user can toggle baseline / recommended

---

# 22. Simulation loading

Use:

```text
ellipsis  ●  ●  ●

Running scenario…
```

Dots animate:
- red
- amber
- green

No spinner.
No glowing “AI thinking.”

---

# 23. Simulation map

Focused corridor view.

Display:
- moving vehicles or simplified vehicle particles
- current queue
- signal locations
- affected road segments
- congestion state
- changed signals

Baseline:
- red / amber queue buildup
- current signal behavior
- observed traffic state

Recommended:
- adjusted signals
- shrinking queue
- improved traffic flow
- red region contracts

Signals that change should be explicitly marked.

Optional detail on click:

```text
Green phase
42s → 51s
```

---

# 24. Simulation metrics

Primary result:

**9.2 seconds saved per vehicle**

Secondary:
- 19% lower average delay
- 5 fewer queued vehicles
- 27% lower corridor congestion
- throughput change where available

Avoid:
- heat score
- optimization score
- AI efficiency

If using heat, label it as something measurable:
- congested road area
- queue pressure
- corridor load

---

# 25. Simulation comparison

V1:
- simple toggle

```text
Baseline | Recommended
```

Do not build a draggable comparison slider unless there is time.

---

# 26. Simulation animation pacing

Suggested demo timing:

0–1.2s:
- ellipsis loading dots

1.2–2.5s:
- map eases into corridor

2.5–4.0s:
- baseline traffic runs

4.0–6.0s:
- signal recommendation appears

6.0–10.0s:
- traffic responds
- queue shrinks

10s:
- metrics settle

The simulation is the most cinematic moment in the product.

---

# 27. Map controls

Two floating groups.

## Data layers

Bottom-left or bottom-center:

```text
[ Incidents ✓ ] [ Traffic ✓ ] [ Cameras ] [ Signals ]
```

Rules:
- no teal selection
- neutral selected state
- incidents always available
- other layers optional

Do not add a separate `Heat` button in v1.

## Navigation

Bottom-right:

```text
[ + ]
[ - ]
[ 3D ]
[ ⟳ ]
```

Keep compact.

---

# 28. Motion and transitions

Motion communicates state change.

Allowed:
- smooth map fly-to
- inspector slides/fades in
- selected road fades into emphasis
- new incident gets one pulse
- camera-source relation fades in
- live freshness updates quietly
- simulation animation
- ellipsis loading dots

Avoid:
- bouncing pins
- continuous pulsing
- glowing borders
- animated gradients
- parallax
- springy overshoot
- “breathing” UI

Support `prefers-reduced-motion`.

---

# 29. Spacing and density

Base spacing system:
- 4px micro
- 8px base
- 12px compact
- 16px standard
- 20–24px major

Panel padding:
- 12–16px in dense operational areas
- 20–24px only where useful

Radius:
- 6–8px controls
- 10–12px panels
- avoid 20px+ pillowy cards

Shadows:
- nearly none
- only subtle separation for floating inspector and map controls

Use:
- typography
- alignment
- separators
- background change

before using cards.

---

# 30. Empty state

Keep map visible.

```text
No active incidents

Traffic conditions are normal in this area.
```

No giant illustration.

---

# 31. Loading state

Initial app load:

```text
ellipsis ● ● ●

Loading live traffic state…
```

Use brand dots.

---

# 32. Stale / delayed data

Camera delayed:

```text
CAM-8AV-033      DELAYED · 18s
```

Traffic stale:

```text
Traffic data delayed 42s
```

Use amber.

Keep last known state available.

---

# 33. Camera offline

```text
CAM-8AV-033      OFFLINE
Last frame 18:46:03
```

Show last frame with dim treatment.

Do not use critical red unless the outage is system-wide.

---

# 34. API / network disconnected

Thin banner:

```text
Connection lost. Showing last known state from 18:48:12.
```

No blocking modal.

---

# 35. Simulation failure

```text
Simulation unavailable

Unable to calculate this scenario with the current traffic state.

Retry
```

No stack traces.

No “AI failed.”

---

# 36. Low-confidence incident

```text
NEEDS REVIEW
Possible stopped vehicle
61% confidence
```

Amber.

---

# 37. Resolved incident

```text
RESOLVED
Double parked vehicle
Cleared at 18:52:14
```

Green is appropriate here.

---

# 38. Responsive behavior

## 1440px+

- 288px incident rail
- full map
- 380px inspector
- full controls
- full simulation

## 1100–1439px

- incident rail collapsible
- inspector 360–380px
- reduced map pitch
- compact top-bar metadata

## 768–1099px

- map full width
- rail becomes left drawer
- inspector becomes bottom sheet
- simulation opens full-screen
- fewer persistent controls

## <768px

Monitoring-first:
- compact status header
- map
- incident list in sheet
- incident detail
- camera feed
- read-only simulation result

No dense operations mode.

Rules:
- rail collapses before inspector
- no horizontal scroll
- camera remains 16:9
- inspector becomes sheet before becoming narrower than ~340px

---

# 39. Iconography

Use one system:
- Lucide preferred

Icons:
- camera
- alert
- clock
- layers
- traffic signal
- map pin
- filter
- chevron
- close
- expand
- rotate
- plus/minus

Style:
- 16–18px
- 1.5–2px stroke
- neutral color by default

Avoid:
- sparkles
- magic wand
- robot
- brain
- AI icons

---

# 40. Accessibility

Minimum:
- WCAG AA text contrast
- status always includes text, not color only
- full keyboard navigation
- accessible map marker labels
- no flashing indicators
- live/replay state explicitly announced
- reduced motion support
- 44px minimum tap targets on touch devices
- camera feed needs descriptive labels
- all simulation state changes need textual metric equivalents

---

# 41. Demo flow

Recommended demo narrative:

### State 1 — Overview
Open on Manhattan.

Show:
- city in 3D
- 12 active incidents
- muted traffic degradation
- incident rail
- no inspector

### State 2 — Select incident
Click a confirmed incident.

System:
- flies toward Midtown
- selected road highlights
- source camera appears
- inspector slides in

### State 3 — Live camera
Inspector shows:
- live source camera
- bounding box
- event freshness
- incident duration
- traffic impact

### State 4 — Trust / detection
Optionally expand detection details.

### State 5 — Response
Click `Open simulation`.

### State 6 — Scenario
Show:
- branded loading dots
- baseline traffic
- changed signal timing
- improved traffic flow

### State 7 — Result
Land on:
- 9.2 seconds saved per vehicle
- 19% lower average delay
- reduced queue
- reduced corridor congestion

---

# 42. Default demo scenario

Suggested state:

- Manhattan / Midtown
- incident at 8th Ave @ W 33rd St
- double parked vehicle
- 4m+ duration
- live camera available
- confidence ~84%
- +22s added delay
- queue estimate ~9 vehicles
- 34% lane capacity reduction
- signal simulation improves average delay ~19%

Two or three additional lower-severity incidents should remain visible to prove city-scale use.

---

# 43. What should never appear

Do not use:

- “AI-powered”
- “smart optimization”
- “AI insight”
- “AI confidence engine”
- robot / brain / sparkle icons
- gradient cards
- glassmorphism
- neon
- giant rounded cards
- giant KPI tiles
- huge confidence rings
- continuous pulse animations
- full-city red/yellow/green road coloring
- fake CCTV chrome
- excessive labels
- teal selection states
- visible `MOCK`
- “hackathon” wording
- arbitrary success scores
- unexplained percentages
- aggressive alert banners for small issues
- giant empty white panel space

---

# 44. Component architecture

Recommended React components:

```text
AppShell
TopBar
BrandMark
ScopeBreadcrumb
SystemHealth
IncidentRail
IncidentRailHeader
IncidentList
IncidentListItem
MapShell
MapLayerControls
MapNavigationControls
CameraMarker
IncidentMarker
IncidentLabel
RoadImpactLayer
IncidentInspector
IncidentHeader
LiveCameraFeed
TrafficImpact
RecommendedResponse
DetectionDetails
IncidentTimeline
SimulationMode
SimulationLoader
SimulationMap
SimulationMetrics
BaselineRecommendedToggle
StatusBanner
EmptyState
OfflineState
```

---

# 45. Incident data model

```ts
type IncidentStatus =
  | "candidate"
  | "needs_review"
  | "confirmed"
  | "critical"
  | "resolved";

type CameraState =
  | "live"
  | "delayed"
  | "offline";

type Incident = {
  id: string;
  type: "double_parked" | "stopped_in_lane";
  status: IncidentStatus;

  location: {
    street: string;
    crossStreet: string;
    borough: string;
    lat: number;
    lng: number;
  };

  startedAt: string;
  durationSeconds: number;
  confidence: number;

  camera: {
    id: string;
    state: CameraState;
    updatedAt: string;
    feedUrl?: string;
  };

  impact: {
    addedDelaySeconds: number;
    queueVehicles: number;
    capacityLossPct: number;
    downstreamSpeedDeltaPct: number;
  };

  detection: {
    stationarySeconds: number;
    inTravelLane: boolean;
    curbOffsetMeters?: number;
    motionScore: number;
    thresholdSeconds: number;
  };

  simulation?: {
    baselineDelaySeconds: number;
    recommendedDelaySeconds: number;
    improvementPct: number;
    queueBefore: number;
    queueAfter: number;
    corridorLoadReductionPct?: number;
  };
};
```

---

# 46. First build priorities

Claude should implement in this order:

1. typography + tokens
2. top bar
3. incident rail
4. 3D map visual treatment
5. incident markers
6. floating inspector
7. live camera block
8. traffic impact
9. detection details
10. simulation teaser
11. focused simulation mode
12. loading/offline/stale states
13. responsive behavior
14. motion polish

Do not polish every secondary control before the core map + incident workflow feels right.

---

# 47. Claude implementation brief

> Redesign the current traffic monitoring interface into a production-grade urban intelligence product called **ellipsis**.
>
> The design direction is **35% infrastructure/control-room and 65% urban-intelligence platform**.
>
> The map must remain the dominant canvas. Use restrained 3D city geometry with muted warm architectural colors, subtle parks and water, and neutral roads. The city should feel alive but never compete with operational state.
>
> Use **Geist** for the UI and **Geist Mono** only for machine data, timestamps, durations, camera IDs, confidence, and simulation metrics.
>
> Use the lowercase wordmark `ellipsis` followed by three small red, amber, and green dots.
>
> Do not use teal as a generic product accent. Green/teal is reserved for healthy/live/resolved states. Amber means degraded or needs review. Coral means confirmed incident. Deep red means severe.
>
> Build a thin 56px top bar, a compact 288px incident rail, a full map canvas, and a 380px floating incident inspector that only appears when an incident is selected.
>
> The incident inspector must prioritize:
> 1. incident
> 2. live camera feed
> 3. traffic impact
> 4. recommended response
> 5. detection details
> 6. timeline
>
> The camera block must behave as a live operational source. Show camera ID, live/replay/delayed/offline state, freshness, timestamp, and restrained object detection overlays.
>
> The map should be minimalist at rest and reveal richer state on interaction. Do not show excessive camera labels or traffic coloring. Selected incidents may reveal affected road segments and source cameras.
>
> The simulation should expand into a focused scenario mode. Use the ellipsis three-dot branded loading state, then show baseline traffic, recommended signal timing, animated queue/traffic response, and clear before/after metrics.
>
> The primary simulation result should be understandable, e.g. seconds saved per vehicle, with secondary metrics for average delay, queue length, congestion/corridor load, and throughput where available.
>
> Avoid all generic AI visual language: no gradients, glassmorphism, neon, sparkle icons, AI labels, confidence rings, giant KPI cards, pill overload, or continuous pulsing.
>
> Use thin borders, 10–12px panel radii, restrained shadows, compact spacing, and warm neutral surfaces.
>
> Implement loading, empty, stale, delayed camera, offline camera, disconnected API, low-confidence incident, resolved incident, and simulation failure states.
>
> The final UI should feel credible enough for a real NYC operations team while remaining visually memorable and strong in a hackathon demo.

---

# 48. Design QA checklist

Do not consider the first pass finished unless all are true:

- map dominates the page
- 3D feels intentional, not decorative
- city is colorful enough to feel alive but muted enough for overlays
- incident rail is scannable in under 2 seconds
- selected state does not use teal
- live camera state is obvious
- replay cannot be confused with live
- confidence is visible but not over-emphasized
- traffic impact is visible above detection details
- simulation is clearly labeled as simulated
- simulation opens into map-focused mode
- time saved is immediately understandable
- changed signals are visible
- loading uses the three brand dots
- no persistent animation is distracting
- no UI section looks like generic AI-generated SaaS
- all state colors have one consistent semantic meaning
- the interface remains useful if data is stale
- the interface remains useful if a camera goes offline
- default state still looks strong with no inspector open
- 30+ incidents do not break the rail
- responsive layout does not crush the map

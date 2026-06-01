// =============================================================================
// Solitaire (Klondike, draw-3) — Arcade game
// =============================================================================
// Contract (see ArcadeApp.jsx):
//   export default function Game({ userId, onGameOver, onExit })
//     - onGameOver(score)  reports a final score (persisted to the leaderboard)
//     - onExit()           returns to the arcade menu
//
// Interaction is click-based (robust on desktop + touch): click the stock to
// deal; click a face-up card to select it (a tableau selection grabs that card
// and everything stacked on it); click a destination pile to move it there;
// double-click a card to auto-send it to a foundation. The in-progress game is
// saved per-user to the server (GET/PUT/DELETE /api/apps/arcade/solitaire/save)
// so you can leave and resume later.
// =============================================================================

import { useState, useEffect, useRef, useCallback } from "react";
import { RotateCcw, ArrowLeft, Trophy, Undo2 } from "lucide-react";

const API = "/api/apps/arcade";
const SUITS = ["s", "h", "d", "c"];
const RED = new Set(["h", "d"]);
const GLYPH = { s: "♠", h: "♥", d: "♦", c: "♣" };
const RANK = { 1: "A", 11: "J", 12: "Q", 13: "K" };
const rankLabel = (r) => RANK[r] || String(r);
const isRed = (s) => RED.has(s);

// ---- pure game logic --------------------------------------------------------

function freshGame() {
  const deck = [];
  for (const s of SUITS) for (let r = 1; r <= 13; r++) deck.push({ id: `${s}${r}`, s, r, up: false });
  for (let i = deck.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [deck[i], deck[j]] = [deck[j], deck[i]];
  }
  const tableau = [[], [], [], [], [], [], []];
  let k = 0;
  for (let col = 0; col < 7; col++) {
    for (let row = 0; row <= col; row++) {
      const card = deck[k++];
      card.up = row === col; // only the last card in each column starts face up
      tableau[col].push(card);
    }
  }
  const stock = deck.slice(k).map((c) => ({ ...c, up: false }));
  return { stock, waste: [], foundations: { s: [], h: [], d: [], c: [] }, tableau, moves: 0, won: false };
}

const clone = (g) => (typeof structuredClone === "function" ? structuredClone(g) : JSON.parse(JSON.stringify(g)));

function canToTableau(card, destPile) {
  if (destPile.length === 0) return card.r === 13; // only a King onto an empty column
  const top = destPile[destPile.length - 1];
  return top.up && top.r === card.r + 1 && isRed(top.s) !== isRed(card.s);
}

function canToFoundation(card, suit, foundations) {
  if (card.s !== suit) return false;
  const f = foundations[suit];
  return f.length === 0 ? card.r === 1 : f[f.length - 1].r === card.r - 1;
}

function isWon(g) {
  return SUITS.every((s) => g.foundations[s].length === 13);
}

// Validate a restored save so a malformed/old blob can't crash the board.
function validSave(g) {
  return (
    g && Array.isArray(g.stock) && Array.isArray(g.waste) &&
    Array.isArray(g.tableau) && g.tableau.length === 7 &&
    g.foundations && SUITS.every((s) => Array.isArray(g.foundations[s]))
  );
}

// ---- component --------------------------------------------------------------

export default function Solitaire({ userId, onGameOver, onExit }) {
  const [game, setGame] = useState(null);          // null = still loading
  const [sel, setSel] = useState(null);            // {zone:'waste'} | {zone:'tableau',col,idx} | {zone:'foundation',suit}
  const reportedRef = useRef(false);               // guard double score submit
  const loadedRef = useRef(false);                 // skip saving the initial load
  const saveTimer = useRef(null);

  const player = (userId || "").trim();

  // --- load saved game (or deal a new one) on mount ---
  useEffect(() => {
    let dead = false;
    (async () => {
      let loaded = null;
      try {
        const res = await fetch(`${API}/solitaire/save?player=${encodeURIComponent(player)}`);
        if (res.ok) {
          const data = await res.json();
          if (validSave(data.state)) loaded = data.state;
        }
      } catch { /* offline — just deal a fresh game */ }
      if (!dead) {
        setGame(loaded || freshGame());
        // allow saves only after this initial state is in place
        setTimeout(() => { loadedRef.current = true; }, 0);
      }
    })();
    return () => { dead = true; };
  }, [player]);

  // --- persist (debounced) whenever the game changes ---
  useEffect(() => {
    if (!game || !loadedRef.current || !player) return;
    if (game.won) return; // a won game is cleared explicitly below
    clearTimeout(saveTimer.current);
    const snapshot = JSON.stringify(game);
    saveTimer.current = setTimeout(() => {
      fetch(`${API}/solitaire/save`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ player, state: JSON.parse(snapshot) }),
      }).catch(() => {});
    }, 600);
    return () => clearTimeout(saveTimer.current);
  }, [game, player]);

  const clearSave = useCallback(() => {
    if (!player) return;
    fetch(`${API}/solitaire/save?player=${encodeURIComponent(player)}`, { method: "DELETE" }).catch(() => {});
  }, [player]);

  const newGame = useCallback(() => {
    reportedRef.current = false;
    setSel(null);
    setGame(freshGame());
  }, []);

  // --- win handling ---
  useEffect(() => {
    if (game && game.won && !reportedRef.current) {
      reportedRef.current = true;
      clearSave();
      // Fewer moves = higher score; floor at a small win bonus.
      const score = Math.max(100, 1200 - game.moves * 3);
      try { onGameOver && onGameOver(score); } catch { /* ignore */ }
    }
  }, [game, clearSave, onGameOver]);

  // --- actions (all produce a new immutable-ish state) ---
  const drawStock = () => {
    setSel(null);
    setGame((prev) => {
      const g = clone(prev);
      if (g.stock.length === 0) {
        // recycle the waste back into the stock, face down, original order
        g.stock = g.waste.reverse().map((c) => ({ ...c, up: false }));
        g.waste = [];
      } else {
        for (let i = 0; i < 3 && g.stock.length; i++) {
          const c = g.stock.pop();
          c.up = true;
          g.waste.push(c);
        }
      }
      g.moves += 1;
      return g;
    });
  };

  // cards currently described by a selection (and their source removal)
  const movingCards = (g, s) => {
    if (!s) return [];
    if (s.zone === "waste") return g.waste.length ? [g.waste[g.waste.length - 1]] : [];
    if (s.zone === "foundation") {
      const f = g.foundations[s.suit];
      return f.length ? [f[f.length - 1]] : [];
    }
    if (s.zone === "tableau") return g.tableau[s.col].slice(s.idx);
    return [];
  };

  const removeSource = (g, s) => {
    if (s.zone === "waste") g.waste.pop();
    else if (s.zone === "foundation") g.foundations[s.suit].pop();
    else if (s.zone === "tableau") {
      g.tableau[s.col].splice(s.idx);
      const col = g.tableau[s.col];
      if (col.length && !col[col.length - 1].up) col[col.length - 1].up = true; // flip newly exposed
    }
  };

  // attempt to move the current selection onto a destination
  const tryMove = (dest) => {
    if (!sel) return;
    setGame((prev) => {
      const g = clone(prev);
      const cards = movingCards(g, sel);
      if (!cards.length) return prev;
      const head = cards[0];
      if (dest.zone === "tableau") {
        if (!canToTableau(head, g.tableau[dest.col])) return prev;
        removeSource(g, sel);
        g.tableau[dest.col].push(...cards.map((c) => ({ ...c, up: true })));
      } else if (dest.zone === "foundation") {
        if (cards.length !== 1 || !canToFoundation(head, dest.suit, g.foundations)) return prev;
        removeSource(g, sel);
        g.foundations[dest.suit].push({ ...head, up: true });
      } else {
        return prev;
      }
      g.moves += 1;
      g.won = isWon(g);
      return g;
    });
    setSel(null);
  };

  // double-click a top card -> auto-send to any valid foundation
  const autoFoundation = (zone, col) => {
    setGame((prev) => {
      const g = clone(prev);
      let card = null, src = null;
      if (zone === "waste" && g.waste.length) { card = g.waste[g.waste.length - 1]; src = { zone: "waste" }; }
      else if (zone === "tableau") {
        const c = g.tableau[col];
        if (c.length && c[c.length - 1].up) { card = c[c.length - 1]; src = { zone: "tableau", col, idx: c.length - 1 }; }
      }
      if (!card) return prev;
      const suit = card.s;
      if (!canToFoundation(card, suit, g.foundations)) return prev;
      removeSource(g, src);
      g.foundations[suit].push({ ...card, up: true });
      g.moves += 1;
      g.won = isWon(g);
      return g;
    });
    setSel(null);
  };

  // click a face-up card: select it, or move the current selection here
  const clickTableauCard = (col, idx) => {
    const card = game.tableau[col][idx];
    if (!card.up) return; // can't pick a face-down card
    if (sel) { tryMove({ zone: "tableau", col }); return; }
    setSel({ zone: "tableau", col, idx });
  };
  const clickTableauEmpty = (col) => { if (sel) tryMove({ zone: "tableau", col }); };
  const clickWaste = () => {
    if (!game.waste.length) return;
    if (sel && !(sel.zone === "waste")) { tryMove({ zone: "waste" }); return; }
    setSel(sel && sel.zone === "waste" ? null : { zone: "waste" });
  };
  const clickFoundation = (suit) => {
    if (sel && sel.zone !== "foundation") { tryMove({ zone: "foundation", suit }); return; }
    if (game.foundations[suit].length) setSel(sel && sel.zone === "foundation" && sel.suit === suit ? null : { zone: "foundation", suit });
  };

  // --- rendering ---
  if (!game) {
    return <div className="flex items-center justify-center h-full text-slate-400 p-10">Loading your game…</div>;
  }

  const selectedKey = (() => {
    if (!sel) return null;
    if (sel.zone === "waste") return game.waste.length ? game.waste[game.waste.length - 1].id : null;
    if (sel.zone === "foundation") { const f = game.foundations[sel.suit]; return f.length ? f[f.length - 1].id : null; }
    if (sel.zone === "tableau") return game.tableau[sel.col][sel.idx]?.id || null;
    return null;
  })();
  const isSelected = (id) => id && id === selectedKey;

  return (
    <div className="h-full flex flex-col bg-emerald-950/40 select-none">
      {/* header */}
      <div className="flex items-center gap-3 px-4 py-2 border-b border-emerald-800/40">
        <button onClick={onExit} className="text-slate-300 hover:text-white inline-flex items-center gap-1 text-sm">
          <ArrowLeft size={15} /> Menu
        </button>
        <span className="text-amber-300 font-semibold">Solitaire</span>
        <span className="text-slate-400 text-xs">moves: {game.moves}</span>
        <div className="ml-auto flex items-center gap-2">
          <button onClick={newGame} className="text-slate-300 hover:text-white inline-flex items-center gap-1 text-sm">
            <RotateCcw size={14} /> New game
          </button>
        </div>
      </div>

      {game.won && (
        <div className="flex items-center justify-center gap-2 bg-amber-500/15 text-amber-300 py-2 text-sm font-medium">
          <Trophy size={16} /> You won in {game.moves} moves! <button onClick={newGame} className="underline ml-2">Deal again</button>
        </div>
      )}

      <div className="flex-1 overflow-auto p-3">
        {/* top row: stock / waste / foundations */}
        <div className="flex gap-2 mb-4">
          <Slot onClick={drawStock} label="↻">
            {game.stock.length ? <CardBack /> : <EmptySlot hint="↻" />}
          </Slot>
          <Slot onClick={clickWaste}>
            {game.waste.length
              ? <Card card={game.waste[game.waste.length - 1]} selected={isSelected(game.waste[game.waste.length - 1].id)} onDoubleClick={() => autoFoundation("waste")} />
              : <EmptySlot />}
          </Slot>
          <div className="w-6" />
          {SUITS.map((s) => {
            const f = game.foundations[s];
            const top = f[f.length - 1];
            return (
              <Slot key={s} onClick={() => clickFoundation(s)}>
                {top ? <Card card={top} selected={isSelected(top.id)} /> : <EmptySlot hint={GLYPH[s]} red={isRed(s)} />}
              </Slot>
            );
          })}
        </div>

        {/* tableau */}
        <div className="flex gap-2">
          {game.tableau.map((col, ci) => (
            <div key={ci} className="flex-1 min-w-[44px]">
              {col.length === 0 ? (
                <Slot onClick={() => clickTableauEmpty(ci)}><EmptySlot /></Slot>
              ) : (
                <div className="relative" style={{ height: `${(col.length - 1) * 22 + 64}px` }}>
                  {col.map((card, ri) => (
                    <div key={card.id} className="absolute left-0" style={{ top: `${ri * 22}px` }}>
                      {card.up
                        ? <Card card={card} selected={isSelected(card.id)} onClick={() => clickTableauCard(ci, ri)} onDoubleClick={() => autoFoundation("tableau", ci)} />
                        : <CardBack onClick={() => {}} />}
                    </div>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>

        <p className="text-slate-500 text-[11px] mt-4">
          Click the deck to draw 3. Click a card to pick it up, then click where it goes. Double-click to send a card to its foundation.
        </p>
      </div>
    </div>
  );
}

// ---- small presentational pieces -------------------------------------------

function Slot({ children, onClick, label }) {
  return (
    <div onClick={onClick} className="w-11 sm:w-14 cursor-pointer" title={label}>
      {children}
    </div>
  );
}

function CardBack({ onClick }) {
  return (
    <div onClick={onClick}
      className="h-16 w-11 sm:w-14 rounded-md border border-sky-300/30 bg-gradient-to-br from-sky-700 to-indigo-800 shadow" />
  );
}

function EmptySlot({ hint, red }) {
  return (
    <div className={`h-16 w-11 sm:w-14 rounded-md border border-dashed border-slate-600/60 flex items-center justify-center text-lg ${red ? "text-rose-400/40" : "text-slate-500/50"}`}>
      {hint || ""}
    </div>
  );
}

function Card({ card, selected, onClick, onDoubleClick }) {
  const red = isRed(card.s);
  return (
    <div
      onClick={onClick}
      onDoubleClick={onDoubleClick}
      className={`h-16 w-11 sm:w-14 rounded-md border bg-white shadow flex flex-col justify-between p-1 cursor-pointer
        ${selected ? "ring-2 ring-amber-400 -translate-y-1" : "border-slate-300"}`}
    >
      <span className={`text-sm font-bold leading-none ${red ? "text-rose-600" : "text-slate-900"}`}>
        {rankLabel(card.r)}<span className="ml-0.5">{GLYPH[card.s]}</span>
      </span>
      <span className={`text-right text-sm leading-none ${red ? "text-rose-600" : "text-slate-900"}`}>{GLYPH[card.s]}</span>
    </div>
  );
}

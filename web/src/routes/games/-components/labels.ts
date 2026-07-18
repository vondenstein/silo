import { GameType, WrapperKind } from "@/lib/api/model"

// One cased label per backend enum value — the edit form and the hero badges
// must show the same word (one-term rule).
export const GAME_TYPE_OPTIONS = [
  { value: GameType.main, label: "Main game" },
  { value: GameType.dlc, label: "DLC" },
  { value: GameType.expansion, label: "Expansion" },
]

export const WRAPPER_OPTIONS = [
  { value: WrapperKind.dosbox, label: "DOSBox" },
  { value: WrapperKind.scummvm, label: "ScummVM" },
]

export function optionLabel(options: { value: string; label: string }[], value: string): string {
  return options.find((option) => option.value === value)?.label ?? value
}

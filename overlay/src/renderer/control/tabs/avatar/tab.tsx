import type { ControlTab } from "../types.ts";
import { AvatarTab } from "./AvatarTab.tsx";

export const tab: ControlTab = {
  id: "avatar",
  title: "Avatar",
  order: 50,
  icon: "☺",
  Component: AvatarTab,
};

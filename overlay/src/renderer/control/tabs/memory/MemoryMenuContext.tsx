import {
  createContext,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";

const Context = createContext<{
  active: string | null;
  setActive: React.Dispatch<React.SetStateAction<string | null>>;
} | null>(null);

/** Facts and notes share one floating menu, including menus rendered through a portal. */
export function MemoryMenuProvider({ children }: { children: ReactNode }) {
  const [active, setActive] = useState<string | null>(null);
  useEffect(() => {
    if (!active) return;
    const outside = (event: PointerEvent) => {
      const target =
        event.target instanceof Element
          ? event.target.closest<HTMLElement>("[data-memory-menu]")
          : null;
      if (target?.dataset.memoryMenu !== active) setActive(null);
    };
    const escape = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      document.getElementById(`${active}-trigger`)?.focus();
      setActive(null);
    };
    document.addEventListener("pointerdown", outside, true);
    document.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("pointerdown", outside, true);
      document.removeEventListener("keydown", escape);
    };
  }, [active]);
  return (
    <Context.Provider value={{ active, setActive }}>
      {children}
    </Context.Provider>
  );
}

export function useMemoryMenu(id: string) {
  const context = useContext(Context);
  if (!context) throw new Error("Memory menus need a MemoryMenuProvider");
  return {
    open: context.active === id,
    setOpen: (open: boolean) =>
      context.setActive((current) =>
        open ? id : current === id ? null : current,
      ),
  };
}

"use client";
import { useTheme } from "next-themes";
import { Monitor, Moon, Sun } from "lucide-react";
import * as Dropdown from "@radix-ui/react-dropdown-menu";
import { Button } from "./ui/button";
export function ThemeToggle() {
  const { setTheme } = useTheme();
  return (
    <Dropdown.Root>
      <Dropdown.Trigger asChild>
        <Button variant="ghost" size="icon" aria-label="Alterar tema">
          <Sun className="theme-sun" size={18} />
          <Moon className="theme-moon" size={18} />
        </Button>
      </Dropdown.Trigger>
      <Dropdown.Portal>
        <Dropdown.Content className="dropdown-content" align="end">
          {[
            { value: "light", label: "Claro", icon: Sun },
            { value: "dark", label: "Escuro", icon: Moon },
            { value: "system", label: "Sistema", icon: Monitor },
          ].map(({ value, label, icon: Icon }) => (
            <Dropdown.Item key={value} className="dropdown-item" onSelect={() => setTheme(value)}>
              <Icon size={16} />
              {label}
            </Dropdown.Item>
          ))}
        </Dropdown.Content>
      </Dropdown.Portal>
    </Dropdown.Root>
  );
}

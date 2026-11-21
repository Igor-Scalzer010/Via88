"use client";

import * as PopoverPrimitive from "@radix-ui/react-popover";
import { cn } from "@/lib/utils";

export const Popover = PopoverPrimitive.Root;
export const PopoverTrigger = PopoverPrimitive.Trigger;

export function PopoverContent({
  className,
  align = "start",
  ...props
}: React.ComponentProps<typeof PopoverPrimitive.Content>) {
  return (
    <PopoverPrimitive.Portal>
      <PopoverPrimitive.Content
        align={align}
        sideOffset={6}
        collisionPadding={12}
        className={cn(
          "popover-content z-[80] max-h-(--radix-popover-content-available-height) max-w-(--radix-popover-content-available-width) origin-(--radix-popover-content-transform-origin) overflow-auto rounded-xl border border-(--border) bg-(--card) text-(--foreground) shadow-xl",
          className,
        )}
        {...props}
      />
    </PopoverPrimitive.Portal>
  );
}

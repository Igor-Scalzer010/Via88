import { Slot } from "@radix-ui/react-slot";
import { cn } from "@/lib/utils";
export function Button({
  className,
  variant = "default",
  size = "default",
  asChild = false,
  ...props
}: React.ComponentProps<"button"> & {
  variant?: "default" | "outline" | "ghost";
  size?: "default" | "icon" | "sm";
  asChild?: boolean;
}) {
  const Component = asChild ? Slot : "button";
  return (
    <Component
      data-slot="button"
      className={cn(
        "button",
        `button-${variant}`,
        size === "icon" && "button-icon",
        size === "sm" && "button-sm",
        className,
      )}
      {...props}
    />
  );
}

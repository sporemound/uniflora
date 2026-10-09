import {
  type ReactNode,
  useCallback,
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import { createPortal } from "react-dom";

interface ViewportInfoPopoverProps {
  title: string;
  ariaLabel: string;
  children: ReactNode;
  triggerText?: string;
  triggerVariant?: "icon" | "tab";
}

interface PopoverPlacement {
  top: number;
  left: number;
  width: number;
  maxHeight: number;
}

/**
 * A shared information control whose open panel is portaled above every
 * scroll/overflow container and clamped to the visible Activity viewport.
 */
export function ViewportInfoPopover({
  title,
  ariaLabel,
  children,
  triggerText = "i",
  triggerVariant = "icon",
}: ViewportInfoPopoverProps) {
  const [open, setOpen] = useState(false);
  const [placement, setPlacement] = useState<PopoverPlacement | null>(null);
  const panelId = useId();
  const titleId = `${panelId}-title`;
  const markerRef = useRef<HTMLSpanElement>(null);
  const popoverRef = useRef<HTMLSpanElement>(null);
  const closeTimerRef = useRef<number | null>(null);

  const cancelDeferredClose = useCallback(() => {
    if (closeTimerRef.current !== null) {
      window.clearTimeout(closeTimerRef.current);
      closeTimerRef.current = null;
    }
  }, []);

  const closePopover = useCallback(
    (restoreFocus = false) => {
      cancelDeferredClose();
      setOpen(false);
      setPlacement(null);
      if (restoreFocus) {
        window.requestAnimationFrame(() => {
          markerRef.current
            ?.querySelector<HTMLButtonElement>(".science-reading-trigger")
            ?.focus();
        });
      }
    },
    [cancelDeferredClose],
  );

  const openPopover = useCallback(() => {
    cancelDeferredClose();
    setOpen(true);
  }, [cancelDeferredClose]);

  const deferClose = useCallback(() => {
    cancelDeferredClose();
    closeTimerRef.current = window.setTimeout(() => {
      closeTimerRef.current = null;
      setOpen(false);
      setPlacement(null);
    }, 140);
  }, [cancelDeferredClose]);

  useEffect(
    () => () => {
      cancelDeferredClose();
    },
    [cancelDeferredClose],
  );

  useEffect(() => {
    if (!open) return;

    const closeOnPointerAway = (event: PointerEvent) => {
      const target = event.target as Node;
      if (
        markerRef.current?.contains(target) ||
        popoverRef.current?.contains(target)
      ) {
        return;
      }
      closePopover();
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        closePopover(true);
      }
    };

    document.addEventListener("pointerdown", closeOnPointerAway);
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("pointerdown", closeOnPointerAway);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, [closePopover, open]);

  useLayoutEffect(() => {
    if (!open) return;

    const positionPopover = () => {
      const marker = markerRef.current;
      const popover = popoverRef.current;
      if (!marker || !popover) return;

      const markerBox = marker.getBoundingClientRect();
      const bodyStyle = window.getComputedStyle(document.body);
      const margin = 12;
      const gap = 8;
      const minimumLeft =
        (Number.parseFloat(bodyStyle.paddingLeft) || 0) + margin;
      const maximumRight =
        document.documentElement.clientWidth -
        (Number.parseFloat(bodyStyle.paddingRight) || 0) -
        margin;
      const minimumTop =
        (Number.parseFloat(bodyStyle.paddingTop) || 0) + margin;
      const maximumBottom =
        window.innerHeight -
        (Number.parseFloat(bodyStyle.paddingBottom) || 0) -
        margin;
      const width = Math.max(
        220,
        Math.min(304, maximumRight - minimumLeft),
      );
      const maxHeight = Math.max(160, maximumBottom - minimumTop);
      const height = Math.min(popover.scrollHeight, maxHeight);
      const left = Math.max(
        minimumLeft,
        Math.min(
          markerBox.left + markerBox.width / 2 - width / 2,
          maximumRight - width,
        ),
      );
      const above = markerBox.top - gap - height;
      const below = markerBox.bottom + gap;
      const top =
        above >= minimumTop
          ? above
          : Math.max(
              minimumTop,
              Math.min(below, maximumBottom - height),
            );

      setPlacement({ top, left, width, maxHeight });
    };

    positionPopover();
    window.addEventListener("resize", positionPopover);
    window.addEventListener("scroll", positionPopover, true);
    return () => {
      window.removeEventListener("resize", positionPopover);
      window.removeEventListener("scroll", positionPopover, true);
    };
  }, [open]);

  const popover =
    open && typeof document !== "undefined"
      ? createPortal(
          <span
            ref={popoverRef}
            id={panelId}
            className="science-reading-popover viewport-info-popover"
            role="dialog"
            aria-labelledby={titleId}
            style={{
              top: placement?.top ?? 0,
              left: placement?.left ?? 0,
              width: placement?.width ?? 304,
              maxHeight: placement?.maxHeight ?? 320,
              visibility: placement ? "visible" : "hidden",
            }}
            onPointerEnter={cancelDeferredClose}
            onPointerLeave={deferClose}
            onFocusCapture={openPopover}
            onBlurCapture={(event) => {
              const next = event.relatedTarget as Node | null;
              if (
                (next && markerRef.current?.contains(next)) ||
                (next && popoverRef.current?.contains(next))
              ) {
                return;
              }
              deferClose();
            }}
          >
            <button
              type="button"
              className="science-reading-close"
              aria-label="Close information"
              onClick={() => closePopover(true)}
            >
              <span aria-hidden="true">×</span>
            </button>
            <strong id={titleId}>{title}</strong>
            {children}
          </span>,
          document.body,
        )
      : null;

  return (
    <>
      <span
        ref={markerRef}
        className={`science-reading-marker viewport-info-marker${
          open ? " is-open" : ""
        }`}
        onPointerEnter={openPopover}
        onPointerLeave={deferClose}
        onFocusCapture={openPopover}
        onBlur={(event) => {
          const next = event.relatedTarget as Node | null;
          if (
            (next && event.currentTarget.contains(next)) ||
            (next && popoverRef.current?.contains(next))
          ) {
            return;
          }
          deferClose();
        }}
      >
        <button
          type="button"
          className={`science-reading-trigger viewport-info-trigger${
            triggerVariant === "tab" ? " is-tab" : ""
          }`}
          aria-label={ariaLabel}
          aria-expanded={open}
          aria-controls={panelId}
          aria-haspopup="dialog"
          onClick={(event) => {
            event.preventDefault();
            event.stopPropagation();
            openPopover();
          }}
        >
          <span aria-hidden="true">{triggerText}</span>
        </button>
      </span>
      {popover}
    </>
  );
}

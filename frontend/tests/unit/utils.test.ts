import { expect, it } from "vitest";
import { formatDate } from "../../src/lib/utils";
it("keeps ISO calendar dates stable in the local timezone", () => {
  expect(formatDate("2025-01-01")).toBe("01/01/2025");
  expect(formatDate("2025-12-31")).toBe("31/12/2025");
  expect(formatDate(null)).toBe("—");
});

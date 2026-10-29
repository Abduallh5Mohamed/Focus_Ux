---
name: Imported test isolation
description: Why the imported Python suites should be verified independently
---

Run the imported API and worker test suites in separate Python processes.

**Why:** Running them together caused collection to resolve the worker's `fakes`
import to the API helper module already cached in Python's module registry.
This is a test-collection collision, not evidence of a worker regression.

**How to apply:** Keep suite invocations separate during setup verification.
A future test-isolation cleanup can replace this workaround with unambiguous
package imports.

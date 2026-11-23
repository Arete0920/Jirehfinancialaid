/**
 * Standalone Jireh synthetic-family read adapter, never a grant or login authority.
 * Provenance: CROWN ParentFinancialAidPreparationPage.jsx's stale-identity and
 * canonical-server-readback rules, adapted to Jireh's UUID household scoping.
 * The actual Django endpoints exist ONLY under disposable test/demo settings.
 * No CROWN auth, token storage, financial writes, or default live transport.
 * Caller MUST increment auth_revision on every session/principal/access change;
 * never pass a cookie, session key or secret as the revision.
 */
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function snapshot(provider) {
  const scope = provider?.();
  if (!scope || !['school_id', 'household_id', 'academic_year_id'].every(k =>
    typeof scope[k] === 'string' && UUID.test(scope[k])) ||
      !Number.isSafeInteger(scope.auth_revision) || scope.auth_revision < 0) {
    throw new Error('Family scope unavailable');
  }
  return Object.freeze({
    school_id: scope.school_id.toLowerCase(),
    household_id: scope.household_id.toLowerCase(),
    academic_year_id: scope.academic_year_id.toLowerCase(),
    auth_revision: scope.auth_revision,
  });
}

function sameScope(a, b) {
  return a.school_id === b.school_id &&
    a.household_id === b.household_id &&
    a.academic_year_id === b.academic_year_id &&
    a.auth_revision === b.auth_revision;
}

function paths(s) {
  const household = `/api/v1/schools/${s.school_id}/households/${s.household_id}/`;
  const draft = `${household}academic-years/${s.academic_year_id}/aid-application/draft/`;
  return {
    household,
    children: `${household}students/`,
    draft,
    selected: `${draft}students/`,
  };
}

function hasValidId(value) {
  return typeof value === 'string' && UUID.test(value);
}

function matchesId(value, expected) {
  return hasValidId(value) && value.toLowerCase() === expected;
}

function validateResult(kind, data, scope) {
  if (!data || typeof data !== 'object' || Array.isArray(data)) {
    throw new Error('Family readback contract invalid');
  }
  if (kind === 'draft') {
    if (!hasValidId(data.id) || data.status !== 'DRAFT' ||
        !matchesId(data.school_id, scope.school_id) ||
        !matchesId(data.household_id, scope.household_id) ||
        !matchesId(data.academic_year_id, scope.academic_year_id)) {
      throw new Error('Family readback scope mismatch');
    }
  } else if (kind === 'household') {
    if (!matchesId(data.id, scope.household_id) || typeof data.name !== 'string') {
      throw new Error('Family readback scope mismatch');
    }
  } else if (kind === 'children') {
    if (!matchesId(data.household_id, scope.household_id) ||
        !Array.isArray(data.students) ||
        !data.students.every(item => hasValidId(item?.id) &&
          typeof item.first_name === 'string' && typeof item.last_name === 'string')) {
      throw new Error('Family readback scope mismatch');
    }
  } else if (kind === 'selected') {
    if (!hasValidId(data.application_id) ||
        !Array.isArray(data.student_ids) ||
        !data.student_ids.every(hasValidId)) {
      throw new Error('Family readback contract invalid');
    }
  }
  return data;
}

export function createFamilyDraftReadClient({fetcher, currentScope, syntheticOnly=false} = {}) {
  async function read(kind) {
    if (syntheticOnly !== true || typeof fetcher !== 'function') {
      throw new Error('Standalone family reads disabled outside explicit synthetic-only test integration');
    }
    const before = snapshot(currentScope);
    let response;
    try {
      response = await fetcher(paths(before)[kind], {
        method: 'GET', credentials: 'same-origin', redirect: 'error',
        cache: 'no-store', headers: { Accept: 'application/json' },
      });
    } catch {
      throw new Error('Family record unavailable');
    }
    if (!sameScope(before, snapshot(currentScope))) {
      throw new Error('Family context changed');
    }
    if (!response?.ok) {
      throw new Error('Family record unavailable');
    }
    let payload;
    try {
      payload = await response.json();
    } catch {
      throw new Error('Family readback contract invalid');
    }
    if (!sameScope(before, snapshot(currentScope))) {
      throw new Error('Family context changed');
    }
    return validateResult(kind, payload, before);
  }
  return Object.freeze({
    readHousehold: () => read('household'),
    readChildren: () => read('children'),
    readDraft: () => read('draft'),
    readSelectedChildren: async () => {
      const originalScope = snapshot(currentScope);
      const draft = await read('draft');
      const selected = await read('selected');
      if (!sameScope(originalScope, snapshot(currentScope))) {
        throw new Error('Family context changed');
      }
      if (!matchesId(selected.application_id, draft.id.toLowerCase())) {
        throw new Error('Family readback scope mismatch');
      }
      return selected;
    },
  });
}

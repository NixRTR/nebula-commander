import React, { useState, useEffect, useCallback } from 'react';
import { Card, Table, Badge, Button, Label, Select, TextInput } from 'flowbite-react';
import { RequireSystemAdmin } from '../components/permissions/RequireSystemAdmin';
import { listAuditLogs, type AuditEntry, type AuditLogParams } from '../api/client';

const LIMIT = 50;
const ACTION_OPTIONS = [
  '',
  'auth_login_success',
  'auth_login_failure',
  'auth_logout',
  'auth_dev_token',
  'device_enroll_success',
  'device_enroll_failure',
  'enrollment_code_created',
  'node_created',
  'node_deleted',
  'node_config_downloaded',
  'node_certs_downloaded',
  'cert_signed',
  'cert_revoked',
  'node_reenrolled',
  'node_request_created',
  'node_request_approved',
  'node_request_rejected',
  'network_created',
  'network_updated',
  'network_deleted',
  'network_group_firewall_updated',
  'network_group_firewall_deleted',
  'user_role_updated',
  'user_deleted',
  'invitation_created',
  'invitation_accepted',
  'invitation_resend',
  'invitation_deleted',
  'network_permission_added',
  'network_permission_updated',
  'network_permission_removed',
  'access_grant_created',
  'access_grant_revoked',
].filter(Boolean);

const RESOURCE_TYPE_OPTIONS = ['', 'user', 'node', 'network', 'invitation', 'node_request'].filter(Boolean);

function formatTimestamp(iso: string): string {
  try {
    const d = new Date(iso);
    return d.toLocaleString();
  } catch {
    return iso;
  }
}

function actorDisplay(entry: AuditEntry): string {
  if (entry.actor_email) return entry.actor_email;
  if (entry.actor_identifier) return entry.actor_identifier;
  return '—';
}

function resourceDisplay(entry: AuditEntry): string {
  const type = entry.resource_type ?? '—';
  const id = entry.resource_id != null ? ` #${entry.resource_id}` : '';
  return `${type}${id}`;
}

export const Audit: React.FC = () => {
  const [entries, setEntries] = useState<AuditEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [filters, setFilters] = useState<AuditLogParams>({
    limit: LIMIT,
    offset: 0,
    action: undefined,
    resource_type: undefined,
    from_date: undefined,
    to_date: undefined,
  });
  const [actionFilter, setActionFilter] = useState('');
  const [resourceTypeFilter, setResourceTypeFilter] = useState('');
  const [fromDateFilter, setFromDateFilter] = useState('');
  const [toDateFilter, setToDateFilter] = useState('');
  const [expandedId, setExpandedId] = useState<number | null>(null);

  const fetchLogs = useCallback(async () => {
    try {
      setLoading(true);
      const params: AuditLogParams = {
        limit: LIMIT,
        offset: filters.offset ?? 0,
        action: filters.action || undefined,
        resource_type: filters.resource_type || undefined,
        from_date: filters.from_date || undefined,
        to_date: filters.to_date || undefined,
      };
      const data = await listAuditLogs(params);
      setEntries(data);
    } catch (error) {
      console.error('Failed to fetch audit logs:', error);
      setEntries([]);
    } finally {
      setLoading(false);
    }
  }, [filters.offset, filters.action, filters.resource_type, filters.from_date, filters.to_date]);

  useEffect(() => {
    fetchLogs();
  }, [fetchLogs]);

  const applyFilters = () => {
    setFilters({
      limit: LIMIT,
      offset: 0,
      action: actionFilter || undefined,
      resource_type: resourceTypeFilter || undefined,
      from_date: fromDateFilter || undefined,
      to_date: toDateFilter || undefined,
    });
  };

  const nextPage = () => {
    setFilters((f) => ({ ...f, offset: (f.offset ?? 0) + LIMIT }));
  };

  const prevPage = () => {
    const newOffset = Math.max(0, (filters.offset ?? 0) - LIMIT);
    setFilters((f) => ({ ...f, offset: newOffset }));
  };

  const hasNext = entries.length === LIMIT;
  const hasPrev = (filters.offset ?? 0) > 0;

  return (
    <RequireSystemAdmin>
      <div>
        <div className="mb-6">
          <h1 className="text-3xl font-bold">Audit Log</h1>
          <p className="mt-2 text-gray-600 dark:text-gray-400">
            View audit trail for sensitive actions (system admins only)
          </p>
        </div>

        <Card className="mb-4">
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 md:grid-cols-4">
            <div>
              <Label htmlFor="audit-action">Action</Label>
              <Select
                id="audit-action"
                value={actionFilter}
                onChange={(e) => setActionFilter(e.target.value)}
              >
                <option value="">All</option>
                {ACTION_OPTIONS.map((a) => (
                  <option key={a} value={a}>
                    {a}
                  </option>
                ))}
              </Select>
            </div>
            <div>
              <Label htmlFor="audit-resource">Resource type</Label>
              <Select
                id="audit-resource"
                value={resourceTypeFilter}
                onChange={(e) => setResourceTypeFilter(e.target.value)}
              >
                <option value="">All</option>
                {RESOURCE_TYPE_OPTIONS.map((r) => (
                  <option key={r} value={r}>
                    {r}
                  </option>
                ))}
              </Select>
            </div>
            <div>
              <Label htmlFor="audit-from">From date</Label>
              <TextInput
                id="audit-from"
                type="datetime-local"
                value={fromDateFilter}
                onChange={(e) => setFromDateFilter(e.target.value)}
              />
            </div>
            <div>
              <Label htmlFor="audit-to">To date</Label>
              <TextInput
                id="audit-to"
                type="datetime-local"
                value={toDateFilter}
                onChange={(e) => setToDateFilter(e.target.value)}
              />
            </div>
          </div>
          <Button className="mt-2" onClick={applyFilters}>
            Apply filters
          </Button>
        </Card>

        {loading ? (
          <Card>
            <p className="text-gray-600 dark:text-gray-400">Loading audit logs...</p>
          </Card>
        ) : entries.length === 0 ? (
          <Card>
            <p className="text-gray-600 dark:text-gray-400">No audit entries found.</p>
          </Card>
        ) : (
          <Card>
            <div className="overflow-x-auto">
              <Table>
                <Table.Head>
                  <Table.HeadCell>Timestamp</Table.HeadCell>
                  <Table.HeadCell>Action</Table.HeadCell>
                  <Table.HeadCell>Actor</Table.HeadCell>
                  <Table.HeadCell>Resource</Table.HeadCell>
                  <Table.HeadCell>Result</Table.HeadCell>
                  <Table.HeadCell>Client IP</Table.HeadCell>
                  <Table.HeadCell>Details</Table.HeadCell>
                </Table.Head>
                <Table.Body>
                  {entries.map((entry) => (
                    <React.Fragment key={entry.id}>
                      <Table.Row>
                        <Table.Cell className="whitespace-nowrap">
                          {formatTimestamp(entry.occurred_at)}
                        </Table.Cell>
                        <Table.Cell>{entry.action}</Table.Cell>
                        <Table.Cell>{actorDisplay(entry)}</Table.Cell>
                        <Table.Cell>{resourceDisplay(entry)}</Table.Cell>
                        <Table.Cell>
                          <Badge color={entry.result === 'success' ? 'success' : 'failure'}>
                            {entry.result}
                          </Badge>
                        </Table.Cell>
                        <Table.Cell>{entry.client_ip ?? '—'}</Table.Cell>
                        <Table.Cell>
                          {entry.details ? (
                            <Button
                              size="xs"
                              color="light"
                              onClick={() =>
                                setExpandedId((id) => (id === entry.id ? null : entry.id))
                              }
                            >
                              {expandedId === entry.id ? 'Hide' : 'Show'}
                            </Button>
                          ) : (
                            '—'
                          )}
                        </Table.Cell>
                      </Table.Row>
                      {expandedId === entry.id && entry.details && (
                        <Table.Row>
                          <Table.Cell colSpan={7} className="bg-gray-50 dark:bg-gray-800">
                            <pre className="text-xs overflow-auto max-h-32 whitespace-pre-wrap break-all">
                              {entry.details}
                            </pre>
                          </Table.Cell>
                        </Table.Row>
                      )}
                    </React.Fragment>
                  ))}
                </Table.Body>
              </Table>
            </div>
            <div className="mt-4 flex items-center gap-4">
              <Button size="sm" disabled={!hasPrev} onClick={prevPage}>
                Previous
              </Button>
              <Button size="sm" disabled={!hasNext} onClick={nextPage}>
                Next
              </Button>
              <span className="text-sm text-gray-600 dark:text-gray-400">
                Showing {entries.length} entries (offset {filters.offset ?? 0})
              </span>
            </div>
          </Card>
        )}
      </div>
    </RequireSystemAdmin>
  );
};

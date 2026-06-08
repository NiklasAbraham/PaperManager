import { useState, useEffect } from "react";
import {
  getProjectMembers,
  addProjectMember,
  updateProjectMemberRole,
  removeProjectMember,
  type ProjectMember,
  apiFetch,
} from "../api/client";

interface Props {
  projectId: string;
  currentUser: string;
  userRole?: string;
}

interface User {
  name: string;
  color?: string;
}

export default function ProjectMembers({ projectId, currentUser, userRole }: Props) {
  const [members, setMembers] = useState<ProjectMember[]>([]);
  const [availableUsers, setAvailableUsers] = useState<User[]>([]);
  const [loading, setLoading] = useState(false);
  const [showAddDialog, setShowAddDialog] = useState(false);
  const [selectedUser, setSelectedUser] = useState("");
  const [selectedRole, setSelectedRole] = useState<"read" | "write" | "admin">("read");
  const [adding, setAdding] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const isAdmin = userRole === "admin";

  useEffect(() => {
    loadMembers();
    loadAvailableUsers();
  }, [projectId]);

  async function loadMembers() {
    try {
      setLoading(true);
      const data = await getProjectMembers(projectId);
      setMembers(data);
    } catch (err) {
      console.error("Failed to load members:", err);
    } finally {
      setLoading(false);
    }
  }

  async function loadAvailableUsers() {
    try {
      const users = await apiFetch<User[]>("/users");
      setAvailableUsers(users);
    } catch (err) {
      console.error("Failed to load users:", err);
    }
  }

  async function handleAddMember() {
    if (!selectedUser) return;
    setAdding(true);
    setError(null);
    try {
      await addProjectMember(projectId, selectedUser, selectedRole);
      await loadMembers();
      setShowAddDialog(false);
      setSelectedUser("");
      setSelectedRole("read");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to add member");
    } finally {
      setAdding(false);
    }
  }

  async function handleUpdateRole(username: string, newRole: "read" | "write" | "admin") {
    try {
      await updateProjectMemberRole(projectId, username, newRole);
      await loadMembers();
    } catch (err) {
      console.error("Failed to update role:", err);
    }
  }

  async function handleRemoveMember(username: string) {
    if (!confirm(`Remove ${username} from this project?`)) return;
    try {
      await removeProjectMember(projectId, username);
      await loadMembers();
    } catch (err) {
      console.error("Failed to remove member:", err);
    }
  }

  function getUserColor(name: string, explicitColor?: string): string {
    if (explicitColor) return explicitColor;
    if (!name?.trim()) return "#94a3b8";
    const palette = ["#7c3aed", "#2563eb", "#0d9488", "#ea580c", "#db2777"];
    const hash = [...name.trim().toLowerCase()].reduce((acc, ch) => acc + ch.charCodeAt(0), 0);
    return palette[hash % palette.length];
  }

  const nonMembers = availableUsers.filter(
    u => !members.some(m => m.username.toLowerCase() === u.name.toLowerCase())
  );

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-gray-700">Project Members</h3>
        {isAdmin && (
          <button
            onClick={() => setShowAddDialog(true)}
            className="px-3 py-1 text-xs font-medium text-violet-700 bg-violet-50 rounded-md hover:bg-violet-100 transition-colors"
          >
            + Add Member
          </button>
        )}
      </div>

      {loading && <p className="text-sm text-gray-400">Loading members...</p>}

      {!loading && members.length === 0 && (
        <p className="text-sm text-gray-400">No members yet. Add team members to collaborate on this project.</p>
      )}

      {!loading && members.length > 0 && (
        <div className="space-y-2">
          {members.map((member) => {
            const color = getUserColor(member.username, member.color);
            const isCurrentUser = member.username.toLowerCase() === currentUser.toLowerCase();

            return (
              <div
                key={member.username}
                className="flex items-center justify-between px-3 py-2 bg-gray-50 rounded-lg"
              >
                <div className="flex items-center gap-2">
                  <div
                    className="w-2 h-2 rounded-full"
                    style={{ backgroundColor: color }}
                  />
                  <span className="text-sm font-medium text-gray-900">
                    {member.username}
                    {isCurrentUser && <span className="ml-1 text-xs text-gray-500">(you)</span>}
                  </span>
                </div>

                <div className="flex items-center gap-2">
                  {isAdmin && !isCurrentUser ? (
                    <select
                      value={member.role}
                      onChange={(e) => handleUpdateRole(member.username, e.target.value as any)}
                      className="text-xs px-2 py-1 border border-gray-200 rounded-md focus:outline-none focus:ring-2 focus:ring-violet-400"
                    >
                      <option value="read">Read</option>
                      <option value="write">Write</option>
                      <option value="admin">Admin</option>
                    </select>
                  ) : (
                    <span className={`text-xs px-2 py-1 rounded-md ${
                      member.role === "admin" ? "bg-violet-100 text-violet-700" :
                      member.role === "write" ? "bg-blue-100 text-blue-700" :
                      "bg-gray-100 text-gray-600"
                    }`}>
                      {member.role}
                    </span>
                  )}

                  {isAdmin && !isCurrentUser && (
                    <button
                      onClick={() => handleRemoveMember(member.username)}
                      className="text-xs text-red-600 hover:text-red-700 px-2 py-1"
                    >
                      Remove
                    </button>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Add Member Dialog */}
      {showAddDialog && (
        <div className="fixed inset-0 bg-black/20 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg shadow-xl p-6 w-full max-w-md">
            <h3 className="text-lg font-semibold text-gray-900 mb-4">Add Project Member</h3>

            {error && (
              <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-md text-sm text-red-700">
                {error}
              </div>
            )}

            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  User
                </label>
                <select
                  value={selectedUser}
                  onChange={(e) => setSelectedUser(e.target.value)}
                  className="w-full px-3 py-2 border border-gray-200 rounded-md focus:outline-none focus:ring-2 focus:ring-violet-400"
                >
                  <option value="">Select a user...</option>
                  {nonMembers.map((user) => (
                    <option key={user.name} value={user.name}>
                      {user.name}
                    </option>
                  ))}
                </select>
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Role
                </label>
                <select
                  value={selectedRole}
                  onChange={(e) => setSelectedRole(e.target.value as any)}
                  className="w-full px-3 py-2 border border-gray-200 rounded-md focus:outline-none focus:ring-2 focus:ring-violet-400"
                >
                  <option value="read">Read - Can view papers and notes</option>
                  <option value="write">Write - Can add papers and edit notes</option>
                  <option value="admin">Admin - Full project management</option>
                </select>
              </div>
            </div>

            <div className="flex gap-2 mt-6">
              <button
                onClick={() => {
                  setShowAddDialog(false);
                  setSelectedUser("");
                  setSelectedRole("read");
                  setError(null);
                }}
                className="flex-1 px-4 py-2 text-sm font-medium text-gray-700 bg-gray-100 rounded-md hover:bg-gray-200 transition-colors"
                disabled={adding}
              >
                Cancel
              </button>
              <button
                onClick={handleAddMember}
                disabled={!selectedUser || adding}
                className="flex-1 px-4 py-2 text-sm font-medium text-white bg-violet-600 rounded-md hover:bg-violet-700 disabled:opacity-50 transition-colors"
              >
                {adding ? "Adding..." : "Add Member"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

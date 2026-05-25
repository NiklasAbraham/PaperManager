import { useState, useEffect } from "react";
import { useAuth } from "../contexts/AuthContext";

const BASE_URL = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

interface User {
  name: string;
  id: string;
  created_at: string;
  is_admin?: boolean;
  paper_count?: number;
  conversation_count?: number;
  note_count?: number;
  connection_count?: number;
}

export default function UserManagement() {
  const { isAdmin, username } = useAuth();
  const [users, setUsers] = useState<User[]>([]);
  const [loading, setLoading] = useState(true);
  const [newUsername, setNewUsername] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  
  // Password update
  const [updateUsername, setUpdateUsername] = useState("");
  const [updatePassword, setUpdatePassword] = useState("");
  const [updating, setUpdating] = useState(false);
  
  // Delete
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);
  const [deletingUser, setDeletingUser] = useState<string | null>(null);

  // Merge users
  const [mergeUserA, setMergeUserA] = useState("");
  const [mergeUserB, setMergeUserB] = useState("");
  const [keepUser, setKeepUser] = useState("");
  const [passwordSourceUser, setPasswordSourceUser] = useState("");
  const [merging, setMerging] = useState(false);

  const canManageTeammates = isAdmin && username?.toLowerCase() === "niklas";

  const fetchUsers = async () => {
    try {
      const token = localStorage.getItem("pm_auth_token");
      const response = await fetch(`${BASE_URL}/auth/admin/users`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (response.ok) {
        const data = await response.json();
        setUsers(data);
      }
    } catch (err) {
      console.error("Failed to fetch users:", err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (isAdmin) {
      fetchUsers();
    }
  }, [isAdmin]);

  const handleCreateUser = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setSuccess("");
    setCreating(true);

    try {
      const token = localStorage.getItem("pm_auth_token");
      const response = await fetch(`${BASE_URL}/auth/admin/create-user`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({ username: newUsername, password: newPassword }),
      });

      if (response.ok) {
        setSuccess(`User "${newUsername}" created successfully`);
        setNewUsername("");
        setNewPassword("");
        fetchUsers();
      } else {
        const data = await response.json();
        setError(data.detail || "Failed to create user");
      }
    } catch (err) {
      setError("Network error");
    } finally {
      setCreating(false);
    }
  };

  const handleUpdatePassword = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setSuccess("");
    setUpdating(true);

    try {
      const token = localStorage.getItem("pm_auth_token");
      const response = await fetch(`${BASE_URL}/auth/admin/update-password`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({ username: updateUsername, new_password: updatePassword }),
      });

      if (response.ok) {
        setSuccess(`Password updated for "${updateUsername}"`);
        setUpdateUsername("");
        setUpdatePassword("");
      } else {
        const data = await response.json();
        setError(data.detail || "Failed to update password");
      }
    } catch (err) {
      setError("Network error");
    } finally {
      setUpdating(false);
    }
  };

  const handleDeleteUser = async (username: string) => {
    setError("");
    setSuccess("");
    setDeletingUser(username);
    try {
      const token = localStorage.getItem("pm_auth_token");
      const response = await fetch(`${BASE_URL}/auth/admin/users/${encodeURIComponent(username)}`, {
        method: "DELETE",
        headers: { Authorization: `Bearer ${token}` },
      });

      if (response.ok) {
        setSuccess(`User "${username}" deleted`);
        fetchUsers();
      } else {
        const text = await response.text();
        try {
          const data = JSON.parse(text);
          setError(data.detail || "Failed to delete user");
        } catch {
          setError(text || "Failed to delete user");
        }
      }
    } catch (err) {
      setError("Network error");
    } finally {
      setDeletingUser(null);
      setConfirmDelete(null);
    }
  };

  const getConnectionCount = (user: User) =>
    (user.paper_count || 0) + (user.conversation_count || 0) + (user.note_count || 0);

  useEffect(() => {
    if (!mergeUserA || !mergeUserB || mergeUserA === mergeUserB) {
      return;
    }
    const userA = users.find((u) => u.name === mergeUserA);
    const userB = users.find((u) => u.name === mergeUserB);
    if (!userA || !userB) {
      return;
    }
    const autoKeep = getConnectionCount(userA) >= getConnectionCount(userB) ? userA.name : userB.name;
    setKeepUser(autoKeep);
    setPasswordSourceUser(autoKeep);
  }, [mergeUserA, mergeUserB, users]);

  const handleMergeUsers = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setSuccess("");

    if (!mergeUserA || !mergeUserB || mergeUserA === mergeUserB) {
      setError("Please select two different users to merge");
      return;
    }

    if (!keepUser || !passwordSourceUser) {
      setError("Please choose which user to keep and which password to keep");
      return;
    }

    setMerging(true);
    try {
      const token = localStorage.getItem("pm_auth_token");
      const response = await fetch(`${BASE_URL}/auth/admin/merge-users`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({
          user_a: mergeUserA,
          user_b: mergeUserB,
          keep_user: keepUser,
          password_source_user: passwordSourceUser,
        }),
      });

      if (response.ok) {
        const data = await response.json();
        setSuccess(
          `Merged users successfully. Kept "${data.kept_user}", removed "${data.removed_user}", moved ${data.moved_papers} papers, ${data.moved_conversations} conversations, and ${data.moved_notes} notes.`
        );
        setMergeUserA("");
        setMergeUserB("");
        setKeepUser("");
        setPasswordSourceUser("");
        fetchUsers();
      } else {
        const text = await response.text();
        try {
          const data = JSON.parse(text);
          setError(data.detail || `Failed to merge users (${response.status})`);
        } catch {
          setError(text || `Failed to merge users (${response.status})`);
        }
      }
    } catch {
      setError("Network error while calling merge endpoint");
    } finally {
      setMerging(false);
    }
  };

  if (!isAdmin) {
    return null;
  }

  if (loading) {
    return <div className="px-5 py-4 text-sm text-gray-500">Loading users...</div>;
  }

  return (
    <div>
      <div className="mb-4">
        <h2 className="text-sm font-semibold text-gray-900">User Management</h2>
        <p className="text-xs text-gray-500 mt-0.5">Create teammates, merge duplicate users, and manage credentials.</p>
      </div>
      <div className="bg-white border border-gray-200 rounded-xl divide-y divide-gray-100">
        {error && (
          <div className="px-5 py-4">
            <div className="p-3 bg-red-50 border border-red-200 text-red-700 rounded-lg text-sm">{error}</div>
          </div>
        )}
        {success && (
          <div className="px-5 py-4">
            <div className="p-3 bg-green-50 border border-green-200 text-green-700 rounded-lg text-sm">{success}</div>
          </div>
        )}

        {!canManageTeammates && (
          <div className="px-5 py-4">
            <div className="p-3 bg-amber-50 border border-amber-200 text-amber-800 rounded-lg text-sm">
              Teammate creation and user merge are restricted to admin user "niklas".
            </div>
          </div>
        )}

        <div className="px-5 py-4">
          <div className="flex items-center justify-between gap-6 mb-3">
            <div>
              <p className="text-sm font-medium text-gray-800">Create New Teammate</p>
              <p className="text-xs text-gray-400 mt-0.5">Available only for admin user niklas.</p>
            </div>
          </div>
          <form onSubmit={handleCreateUser} className="grid grid-cols-1 md:grid-cols-3 gap-3">
            <input
              type="text"
              value={newUsername}
              onChange={(e) => setNewUsername(e.target.value)}
              required
              disabled={!canManageTeammates}
              className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-violet-500 focus:border-violet-500"
              placeholder="Username"
            />
            <input
              type="password"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              required
              minLength={8}
              disabled={!canManageTeammates}
              className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-violet-500 focus:border-violet-500"
              placeholder="Password (min 8 chars)"
            />
            <button
              type="submit"
              disabled={creating || !canManageTeammates}
              className="px-4 py-2 text-sm font-medium bg-violet-600 text-white rounded-lg hover:bg-violet-700 disabled:opacity-50 transition-colors"
            >
              {creating ? "Creating..." : "Create Teammate"}
            </button>
          </form>
        </div>

        <div className="px-5 py-4">
          <div className="flex items-center justify-between gap-6 mb-3">
            <div>
              <p className="text-sm font-medium text-gray-800">Merge Two Users</p>
              <p className="text-xs text-gray-400 mt-0.5">Defaults to keeping the user with more connections. You can override keep-user and password source.</p>
            </div>
          </div>
          <form onSubmit={handleMergeUsers} className="space-y-3">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              <select
                value={mergeUserA}
                onChange={(e) => setMergeUserA(e.target.value)}
                required
                disabled={!canManageTeammates}
                className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-violet-500 focus:border-violet-500"
              >
                <option value="">User A</option>
                {users.map((user) => (
                  <option key={`a-${user.name}`} value={user.name}>
                    {user.name} ({getConnectionCount(user)} connections)
                  </option>
                ))}
              </select>
              <select
                value={mergeUserB}
                onChange={(e) => setMergeUserB(e.target.value)}
                required
                disabled={!canManageTeammates}
                className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-violet-500 focus:border-violet-500"
              >
                <option value="">User B</option>
                {users.map((user) => (
                  <option key={`b-${user.name}`} value={user.name}>
                    {user.name} ({getConnectionCount(user)} connections)
                  </option>
                ))}
              </select>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              <select
                value={keepUser}
                onChange={(e) => setKeepUser(e.target.value)}
                required
                disabled={!canManageTeammates || !mergeUserA || !mergeUserB || mergeUserA === mergeUserB}
                className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-violet-500 focus:border-violet-500"
              >
                <option value="">Keep This User</option>
                {[mergeUserA, mergeUserB].filter(Boolean).map((name) => (
                  <option key={`keep-${name}`} value={name}>{name}</option>
                ))}
              </select>
              <select
                value={passwordSourceUser}
                onChange={(e) => setPasswordSourceUser(e.target.value)}
                required
                disabled={!canManageTeammates || !mergeUserA || !mergeUserB || mergeUserA === mergeUserB}
                className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-violet-500 focus:border-violet-500"
              >
                <option value="">Keep Password From</option>
                {[mergeUserA, mergeUserB].filter(Boolean).map((name) => (
                  <option key={`pwd-${name}`} value={name}>{name}</option>
                ))}
              </select>
            </div>
            <button
              type="submit"
              disabled={merging || !canManageTeammates}
              className="px-4 py-2 text-sm font-medium bg-orange-600 text-white rounded-lg hover:bg-orange-700 disabled:opacity-50 transition-colors"
            >
              {merging ? "Merging..." : "Merge Users"}
            </button>
          </form>
        </div>

        <div className="px-5 py-4">
          <div className="flex items-center justify-between gap-6 mb-3">
            <div>
              <p className="text-sm font-medium text-gray-800">Update User Password</p>
              <p className="text-xs text-gray-400 mt-0.5">Change password for an existing user.</p>
            </div>
          </div>
          <form onSubmit={handleUpdatePassword} className="grid grid-cols-1 md:grid-cols-3 gap-3">
            <select
              value={updateUsername}
              onChange={(e) => setUpdateUsername(e.target.value)}
              required
              className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-violet-500 focus:border-violet-500"
            >
              <option value="">Select user</option>
              {users.map((user) => (
                <option key={user.name} value={user.name}>
                  {user.name}
                </option>
              ))}
            </select>
            <input
              type="password"
              value={updatePassword}
              onChange={(e) => setUpdatePassword(e.target.value)}
              required
              minLength={8}
              className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-violet-500 focus:border-violet-500"
              placeholder="New password"
            />
            <button
              type="submit"
              disabled={updating}
              className="px-4 py-2 text-sm font-medium bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 transition-colors"
            >
              {updating ? "Updating..." : "Update Password"}
            </button>
          </form>
        </div>

        <div className="px-5 py-4">
          <p className="text-sm font-medium text-gray-800 mb-3">Existing Users ({users.length})</p>
          <div className="border border-gray-200 rounded-lg overflow-hidden">
            <table className="min-w-full divide-y divide-gray-200 text-sm">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Username</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Role</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Papers</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Conversations</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Notes</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Connections</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Created</th>
                  <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">Actions</th>
                </tr>
              </thead>
              <tbody className="bg-white divide-y divide-gray-200">
                {users.map((user) => (
                  <tr key={user.name}>
                    <td className="px-4 py-3 text-sm font-medium text-gray-900">{user.name}</td>
                    <td className="px-4 py-3 text-sm text-gray-500">
                      {user.is_admin ? (
                        <span className="px-2 py-1 text-xs font-semibold text-violet-700 bg-violet-100 rounded">Admin</span>
                      ) : (
                        <span className="text-gray-400">User</span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-sm text-gray-500">{user.paper_count || 0}</td>
                    <td className="px-4 py-3 text-sm text-gray-500">{user.conversation_count || 0}</td>
                    <td className="px-4 py-3 text-sm text-gray-500">{user.note_count || 0}</td>
                    <td className="px-4 py-3 text-sm text-gray-500">{getConnectionCount(user)}</td>
                    <td className="px-4 py-3 text-sm text-gray-500">
                      {user.created_at ? new Date(user.created_at).toLocaleDateString() : "—"}
                    </td>
                    <td className="px-4 py-3 text-sm text-right">
                      {confirmDelete === user.name ? (
                        <div className="flex gap-2 justify-end">
                          <button
                            onClick={() => handleDeleteUser(user.name)}
                            disabled={deletingUser === user.name}
                            className="px-2 py-1 text-xs bg-red-600 text-white rounded hover:bg-red-700"
                          >
                            {deletingUser === user.name ? "Deleting..." : "Confirm"}
                          </button>
                          <button
                            onClick={() => setConfirmDelete(null)}
                            disabled={deletingUser === user.name}
                            className="px-2 py-1 text-xs bg-gray-300 text-gray-700 rounded hover:bg-gray-400"
                          >
                            Cancel
                          </button>
                        </div>
                      ) : (
                        <button
                          onClick={() => setConfirmDelete(user.name)}
                          disabled={user.name === username}
                          className="px-3 py-1 text-xs text-red-600 hover:text-red-800 disabled:text-gray-400 disabled:cursor-not-allowed"
                        >
                          {user.name === username ? "Current user" : "Delete"}
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  );
}

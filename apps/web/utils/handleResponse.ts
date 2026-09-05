export const handleResponse = async (response: Response) => {
  if (response.status === 204) return;
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data?.message || 'API request failed');
  }
  return data;
};

import { useState, useEffect, useContext } from 'react';
import { UserContext } from '@/context/UserContext';

interface Category {
  category: string;
  icon: string | null;
}

interface CategoriesResponse {
  categories: Category[];
}

export const useCategories = (language: string) => {
  const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
  const { fetchWithAuth } = useContext(UserContext);
  const [categories, setCategories] = useState<Category[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const fetchCategories = async () => {
      setIsLoading(true);
      setError(null);
      try {
        const response = await fetchWithAuth(`${API_URL}/categories/videos?language=${language}`);
        if (!response.ok) {
          throw new Error(`HTTP error! status: ${response.status}`);
        }
        const responseData = await response.json();
        if (!responseData.categories) {
          throw new Error('Categories data not found in response');
        }
        setCategories(responseData.categories);
      } catch (err) {
        setError(err instanceof Error ? err.message : 'An error occurred while fetching categories');
      } finally {
        setIsLoading(false);
      }
    };

    fetchCategories();
  }, [language, API_URL, fetchWithAuth]);

  return { categories, isLoading, error };
};
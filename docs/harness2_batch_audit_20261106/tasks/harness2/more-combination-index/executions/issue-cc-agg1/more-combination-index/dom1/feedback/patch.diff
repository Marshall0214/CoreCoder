--- a/more_itertools/more.py
+++ b/more_itertools/more.py
@@ -4517,43 +4517,52 @@
     """
     element = tuple(element)
     l = len(element)
-    element = enumerate(element)
-
-    k, y = next(element, (None, None))
-    if k is None:
+    
+    pool = tuple(iterable)
+    n = len(pool)
+    
+    # Validate that every item in element exists in pool and is non-decreasing
+    prev_idx = -1
+    for e in element:
+        try:
+            curr_idx = pool.index(e)
+        except ValueError:
+            raise ValueError(
+                'element is not a combination with replacement of iterable'
+            )
+        if curr_idx < prev_idx:
+            raise ValueError(
+                'element is not a combination with replacement of iterable'
+            )
+        prev_idx = curr_idx
+
+    if l == 0:
         return 0
 
-    indexes = []
-    pool = tuple(iterable)
-    for n, x in enumerate(pool):
-        while x == y:
-            indexes.append(n)
-            tmp, y = next(element, (None, None))
-            if tmp is None:
-                break
-            else:
-                k = tmp
-        if y is None:
-            break
-    else:
-        raise ValueError(
-            'element is not a combination with replacement of iterable'
-        )
-
-    n = len(pool)
-    occupations = [0] * n
-    for p in indexes:
-        occupations[p] += 1
-
+    # Calculate index using combinatorial number system for combinations with replacement
+    # The formula sums up the number of combinations that come before the current one
     index = 0
-    cumulative_sum = 0
-    for k in range(1, n):
-        cumulative_sum += occupations[k - 1]
-        j = l + n - 1 - k - cumulative_sum
-        i = n - k
-        if i <= j:
-            index += comb(j, i)
-
+    for i, e in enumerate(element):
+        curr_idx = pool.index(e)
+        # For each position, count how many valid combinations start with a smaller element
+        # or have the same prefix but a smaller element at this position
+        if i == 0:
+            # First element: count all combinations starting with elements before curr_idx
+            index += comb(curr_idx + l - 1, l)
+        else:
+            # Subsequent elements: count combinations with same prefix but smaller current element
+            # We need to account for the fact that we can't go below the previous element's index
+            prev_e = element[i-1]
+            prev_idx_val = pool.index(prev_e)
+            
+            # Count valid choices for this position that are >= prev_idx_val and < curr_idx
+            start_idx = prev_idx_val
+            end_idx = curr_idx
+            remaining_len = l - i
+            
+            for j in range(start_idx, end_idx):
+                index += comb(j + remaining_len - 1, remaining_len)
+    
     return index
 
 

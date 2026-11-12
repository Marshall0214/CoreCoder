--- a/more_itertools/more.py
+++ b/more_itertools/more.py
@@ -4517,30 +4517,35 @@
     """
     element = tuple(element)
     l = len(element)
-    element = enumerate(element)
-
-    k, y = next(element, (None, None))
-    if k is None:
+    
+    # Handle empty combination
+    if l == 0:
         return 0
 
+    pool = tuple(iterable)
+    n = len(pool)
+    
+    # Validate that all elements in 'element' are in the pool
+    # and that the element is non-decreasing according to pool order
     indexes = []
-    pool = tuple(iterable)
-    for n, x in enumerate(pool):
-        while x == y:
-            indexes.append(n)
-            tmp, y = next(element, (None, None))
-            if tmp is None:
+    for elem_val in element:
+        found = False
+        for idx, pool_val in enumerate(pool):
+            if pool_val == elem_val:
+                # Check non-decreasing: current index must be >= last index
+                if indexes and idx < indexes[-1]:
+                    raise ValueError(
+                        'element is not a combination with replacement of iterable'
+                    )
+                indexes.append(idx)
+                found = True
                 break
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
+        if not found:
+            raise ValueError(
+                'element is not a combination with replacement of iterable'
+            )
+
+    # Calculate the index using combinatorial formula
     occupations = [0] * n
     for p in indexes:
         occupations[p] += 1

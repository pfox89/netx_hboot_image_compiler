Changes to original version of hboot compiler:

- hboot compiler creates a '.sniplib.dblite' file in working directory
  when executed. Such a behavior is unexpected (unexpected file created),
  can fail if hboot is exectued from a read only directory and
  breaks waf parallel build. 

  For waf this had modified to become an In-Memory database 


